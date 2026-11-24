$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.7 - Adaptation / Replanning E2E Scenario"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.7-adaptation-replanning-e2e-scenario"
$ExpectedMigration = 53
$ExpectedInventory = 1531
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_7_adaptation_replanning_schema_version -ne "apts-stage3.9-adaptation-replanning-e2e-scenario-v1") { throw "Stage 3.9.7 schema inactive" }
if (-not $health.stage3_9_7_runtime_verifier_read_only) { throw "Stage 3.9.7 verifier is not read-only" }
if (-not $health.stage3_9_7_authoritative_governance_required) { throw "authoritative Governance requirement inactive" }
if ([int]$health.stage3_9_7_successor_plan_version_expected -ne 2) { throw "successor Plan v2 expectation inactive" }
if ($health.stage3_9_7_recovery_checkpoint_performed) { throw "premature Stage 3.7.9 recovery checkpoint declared" }
if ($health.stage3_9_7_routing_performed_after_handoff) { throw "premature routing declared" }
if ($health.stage3_9_7_dispatch_performed_after_handoff) { throw "premature dispatch declared" }
if ($health.stage3_9_7_target_actuation) { throw "unexpected target actuation declared" }
if ($health.stage3_9_7_new_database_migration_added -or $health.stage3_9_7_new_durable_store_added) { throw "unexpected Stage 3.9.7 persistence expansion" }
if ($health.stage3_9_7_new_replan_authority_added) { throw "unexpected Stage 3.9.7 authority expansion" }
if ($health.stage3_9_7_next_stage -ne "3.9.8") { throw "next-stage health mismatch" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/adaptation-replanning-qualification-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.predecessor_control -ne "stage3.9.6-task-completion-mission-outcome-closure") { throw "predecessor mismatch" }
if ([int]$contract.definition.successor_plan_version_expected -ne 2) { throw "successor-plan contract mismatch" }
if ($contract.definition.handoff_next_control -ne "STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH") { throw "handoff-next-control mismatch" }
if ($contract.definition.stage3_7_9_recovery_checkpoint_expected) { throw "contract incorrectly expects Stage 3.7.9 checkpoint" }
if ($contract.definition.next_stage -ne "3.9.8") { throw "next-stage contract mismatch" }
Write-Host "[PASS] Stage 3.9.7 contract route"

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

Write-Host "`n[4] Focused Stage 3.9.7"
python -m pytest -q tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.7 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E predecessor chain"
python -m pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py `
  tests/test_stage3_9_6_task_completion_mission_outcome_closure.py `
  tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Adaptation / replanning authority regression"
python -m pytest -q `
  tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py `
  tests/test_stage3_7_2_adaptation_trigger_detection_classification.py `
  tests/test_stage3_7_3_replan_eligibility_governance_gate.py `
  tests/test_stage3_7_4_canonical_replan_snapshot_context_binding.py `
  tests/test_stage3_7_5_deterministic_replan_candidate_generation.py `
  tests/test_stage3_7_6_replan_candidate_validation_delta_feasibility_gate.py `
  tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py `
  tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py `
  tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py `
  tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.7 adaptation/replanning authority regression failed" }

Write-Host "`n[7] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.7 Adaptation / Replanning E2E Scenario"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "canonical head  : RUNNING(v4), Plan v2 ACTIVE, HANDOFF_READY"
Write-Host "boundary        : no Stage 3.7.9 checkpoint / no new routing-dispatch-actuation"
Write-Host "next            : Stage 3.9.8 - Restart / Replay / Recovery"
Write-Host "=============================================================================="
