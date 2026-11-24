$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.6 - Task Completion -> Mission Outcome Closure"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.6-task-completion-mission-outcome-closure"
$ExpectedMigration = 53
$ExpectedInventory = 1515
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_6_completion_outcome_schema_version -ne "apts-stage3.9-task-completion-mission-outcome-closure-v1") { throw "Stage 3.9.6 schema inactive" }
if (-not $health.stage3_9_6_runtime_verifier_read_only) { throw "Stage 3.9.6 verifier is not read-only" }
if (-not $health.stage3_9_6_task_completion_requires_verified_evidence) { throw "verified-evidence completion requirement inactive" }
if (-not $health.stage3_9_6_completion_readiness_expected_blocked) { throw "canonical blocked-readiness expectation inactive" }
if ($health.stage3_9_6_verified_completion_performed) { throw "premature verified completion declared" }
if ($health.stage3_9_6_mission_state_transition_performed) { throw "premature mission lifecycle transition declared" }
if (-not $health.stage3_9_6_adaptation_replan_handoff_required) { throw "Stage 3.9.7 handoff inactive" }
if ($health.stage3_9_6_new_database_migration_added -or $health.stage3_9_6_new_durable_store_added) { throw "unexpected Stage 3.9.6 persistence expansion" }
if ($health.stage3_9_6_new_completion_authority_added) { throw "unexpected Stage 3.9.6 completion authority expansion" }
if ($health.stage3_9_6_next_stage -ne "3.9.7") { throw "next-stage health mismatch" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/completion-outcome-qualification-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.predecessor_control -ne "stage3.9.5-dispatch-execution-evidence-continuity") { throw "predecessor mismatch" }
if ($contract.definition.next_stage -ne "3.9.7") { throw "next-stage mismatch" }
if (-not $contract.definition.blocked_readiness_expected) { throw "contract blocked-readiness expectation missing" }
if ($contract.definition.verified_completion_expected) { throw "contract incorrectly expects verified completion" }
if (-not $contract.definition.adaptation_replan_handoff_required) { throw "contract Stage 3.9.7 handoff missing" }
Write-Host "[PASS] Stage 3.9.6 contract route"

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

Write-Host "`n[4] Focused Stage 3.9.6"
python -m pytest -q tests/test_stage3_9_6_task_completion_mission_outcome_closure.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.6 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E predecessor chain"
python -m pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py `
  tests/test_stage3_9_6_task_completion_mission_outcome_closure.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Terminal execution / outcome authority regression"
python -m pytest -q `
  tests/test_stage3_5_8_timeout_cancellation_abort_failure_propagation.py `
  tests/test_stage3_5_9_execution_event_lineage_replay_recovery.py `
  tests/test_stage3_6_1_canonical_task_outcome_contract_identity.py `
  tests/test_stage3_6_2_task_terminality_completion_eligibility.py `
  tests/test_stage3_6_3_evidence_binding_verification.py `
  tests/test_stage3_6_4_dependency_aware_task_completion.py `
  tests/test_stage3_6_5_mission_outcome_aggregation.py `
  tests/test_stage3_6_6_mission_success_criteria_evaluation.py `
  tests/test_stage3_6_7_completion_readiness_blockers.py `
  tests/test_stage3_6_8_verified_completion_declaration_lifecycle_handoff.py `
  tests/test_stage3_6_9_outcome_lineage_replay_recovery.py `
  tests/test_stage3_6_10_outcome_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.5.8/3.5.9 + Stage 3.6 outcome regression failed" }

Write-Host "`n[7] Full historical regression"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.6 Task Completion -> Mission Outcome Closure"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "canonical head  : RUNNING(v4), readiness BLOCKED, no verified completion"
Write-Host "next            : Stage 3.9.7 - Adaptation & Replanning"
Write-Host "=============================================================================="
