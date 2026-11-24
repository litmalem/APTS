$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.9 - Global Observation / Reconstruction / Forensic Equivalence"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.9-global-observation-reconstruction-forensic-equivalence"
$ExpectedMigration = 53
$ExpectedInventory = 1560
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_9_observation_reconstruction_forensic_schema_version -ne "apts-stage3.9-global-observation-reconstruction-forensic-equivalence-v1") { throw "Stage 3.9.9 schema inactive" }
if (-not $health.stage3_9_9_runtime_verifier_read_only) { throw "Stage 3.9.9 verifier is not read-only" }
if (-not $health.stage3_9_9_forensic_equivalence_required) { throw "forensic equivalence is not required" }
if ($health.stage3_9_9_predecessor_control -ne "stage3.9.8-restart-replay-recovery-e2e-verification") { throw "predecessor health mismatch" }
if ([int]$health.stage3_9_9_expected_repository_migration_level -ne 53) { throw "Stage 3.9.9 expected migration mismatch" }
if ($health.stage3_9_9_new_database_migration_added -or $health.stage3_9_9_new_durable_store_added) { throw "unexpected Stage 3.9.9 persistence expansion" }
if ($health.stage3_9_9_new_observation_authority_added -or $health.stage3_9_9_new_forensic_authority_added) { throw "unexpected Stage 3.9.9 authority expansion" }
if ($health.stage3_9_9_forensic_bundle_external_attestation) { throw "forensic bundle incorrectly declared external attestation" }
if ($health.stage3_9_9_reconstruction_runtime_resumption -or $health.stage3_9_9_reconstruction_mission_reexecution) { throw "reconstruction boundary mismatch" }
if ($health.stage3_9_9_integrity_repair_performed -or $health.stage3_9_9_governance_query_performed -or $health.stage3_9_9_runtime_query_performed) { throw "unexpected Stage 3.9.9 side effect declared" }
if ($health.stage3_9_9_telemetry_export_performed -or $health.stage3_9_9_external_network_io_performed -or $health.stage3_9_9_target_actuation) { throw "unexpected Stage 3.9.9 I/O/actuation declared" }
if ($health.stage3_9_9_next_stage -ne "3.9.10") { throw "next-stage health mismatch" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/observation-reconstruction-forensic-equivalence-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.predecessor_control -ne "stage3.9.8-restart-replay-recovery-e2e-verification") { throw "predecessor contract mismatch" }
if ([int]$contract.definition.expected_repository_migration_level -ne 53) { throw "contract migration mismatch" }
if ([int]$contract.definition.mission_event_count_expected -ne 50) { throw "mission event count mismatch" }
if ([int]$contract.definition.normalized_event_count_expected -ne 50) { throw "normalized event count mismatch" }
if ([int]$contract.definition.timeline_event_count_expected -ne 50) { throw "timeline event count mismatch" }
if ([int]$contract.definition.causal_node_count_expected -ne 51 -or [int]$contract.definition.causal_edge_count_expected -ne 50) { throw "causal graph cardinality mismatch" }
if ($contract.definition.diagnostics_status_expected -ne "PASS") { throw "diagnostics expectation mismatch" }
if ($contract.definition.observability_health_expected -ne "HEALTHY") { throw "observability health expectation mismatch" }
if ($contract.definition.forensic_bundle_status_expected -ne "VERIFIED" -or $contract.definition.forensic_reconstruction_status_expected -ne "VERIFIED" -or $contract.definition.forensic_query_status_expected -ne "VERIFIED") { throw "forensic status expectation mismatch" }
if (-not $contract.definition.forensic_equivalence_required) { throw "contract does not require equivalence" }
if ($contract.definition.next_stage -ne "3.9.10") { throw "next-stage contract mismatch" }
Write-Host "[PASS] Stage 3.9.9 contract route"

Write-Host "`n[2] Python compilation"
python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[3] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[4] Focused Stage 3.9.9"
python -m pytest -q tests/test_stage3_9_9_global_observation_reconstruction_forensic_equivalence.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.9 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E chain"
python -m pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py `
  tests/test_stage3_9_6_task_completion_mission_outcome_closure.py `
  tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py `
  tests/test_stage3_9_9_global_observation_reconstruction_forensic_equivalence.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Observation / reconstruction / forensic authority regression"
python -m pytest -q `
  tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py `
  tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py `
  tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py `
  tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py `
  tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py `
  tests/test_stage3_9_9_global_observation_reconstruction_forensic_equivalence.py
if ($LASTEXITCODE -ne 0) { throw "observation/reconstruction/forensic regression failed" }

Write-Host "`n[7] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.9 Global Observation / Reconstruction / Forensic Equivalence"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "canonical head  : RUNNING(v4), Plan v2 ACTIVE, 50 canonical mission events"
Write-Host "observation     : normalized=50, timeline=50, causal graph=51 nodes/50 edges"
Write-Host "forensics       : bundle/reconstruction/queries VERIFIED, global equivalence PASS"
Write-Host "boundary        : read-only; no repair / reexecution / runtime resumption / external attestation / actuation"
Write-Host "next            : Stage 3.9.10 - Final Acceptance & Regression Gate"
Write-Host "=============================================================================="
