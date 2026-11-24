$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.8 - Restart / Replay / Recovery E2E Verification"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.8-restart-replay-recovery-e2e-verification"
$ExpectedMigration = 53
$ExpectedInventory = 1545
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_8_restart_replay_recovery_schema_version -ne "apts-stage3.9-restart-replay-recovery-e2e-verification-v1") { throw "Stage 3.9.8 schema inactive" }
if (-not $health.stage3_9_8_runtime_verifier_read_only) { throw "Stage 3.9.8 verifier is not read-only" }
if ($health.stage3_9_8_restart_source -ne "DURABLE_REPOSITORY_ONLY") { throw "restart source mismatch" }
if ([int]$health.stage3_9_8_recovery_checkpoint_count_expected -ne 1) { throw "checkpoint cardinality expectation mismatch" }
if ($health.stage3_9_8_recovery_consistency_expected -ne "PASS") { throw "recovery consistency expectation mismatch" }
if ($health.stage3_9_8_new_database_migration_added -or $health.stage3_9_8_new_durable_store_added) { throw "unexpected Stage 3.9.8 persistence expansion" }
if ($health.stage3_9_8_new_recovery_authority_added) { throw "unexpected Stage 3.9.8 authority expansion" }
if ($health.stage3_9_8_target_actuation) { throw "unexpected target actuation declared" }
if ($health.stage3_9_8_next_stage -ne "3.9.9") { throw "next-stage health mismatch" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/restart-replay-recovery-qualification-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.predecessor_control -ne "stage3.9.7-adaptation-replanning-e2e-scenario") { throw "predecessor mismatch" }
if ($contract.definition.restart_source -ne "DURABLE_REPOSITORY_ONLY") { throw "restart-source contract mismatch" }
if ([int]$contract.definition.replan_event_count_expected -ne 10) { throw "replan replay cardinality mismatch" }
if ([int]$contract.definition.mission_event_count_expected -ne 50) { throw "mission event cardinality mismatch" }
if ($contract.definition.next_stage -ne "3.9.9") { throw "next-stage contract mismatch" }
Write-Host "[PASS] Stage 3.9.8 contract route"

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

Write-Host "`n[4] Focused Stage 3.9.8"
python -m pytest -q tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.8 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E predecessor chain"
python -m pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py `
  tests/test_stage3_9_6_task_completion_mission_outcome_closure.py `
  tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Recovery authority regression"
python -m pytest -q `
  tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py `
  tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py `
  tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py `
  tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py
if ($LASTEXITCODE -ne 0) { throw "restart/replay/recovery authority regression failed" }

Write-Host "`n[7] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.8 Restart / Replay / Recovery E2E Verification"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "canonical head  : RUNNING(v4), Plan v2 ACTIVE, recovery checkpoint persisted"
Write-Host "replay          : 10 replan events / 50 mission events, deterministic after restart"
Write-Host "boundary        : no planner rerun / governance query / runtime I/O / routing-dispatch-actuation"
Write-Host "next            : Stage 3.9.9 - Observation / Reconstruction / Forensic Equivalence"
Write-Host "=============================================================================="
