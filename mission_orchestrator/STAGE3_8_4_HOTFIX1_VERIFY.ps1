$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 3.8.4 Hotfix 1 - Regression Baseline Rebase Verification"
Write-Host "=============================================================================="

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python compilation failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] Python compilation"

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1389 tests collected') {
    Write-Host "[FAIL] canonical inventory must contain 1389 tests" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] 1389 tests collected"

$tests = @(
  "tests/test_stage3_1_10_acceptance_regression_gate.py::test_stage3110_health_declares_closure_gate_and_all_prior_controls",
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_health_declares_stage34_closure_without_new_authority_or_migration",
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered",
  "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed",
  "tests/test_stage3_6_10_outcome_acceptance_regression_gate.py::test_01_health_activates_stage3610_closure_without_new_migration",
  "tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py::test_health_activates_stage371_contract_identity_and_migration_45",
  "tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py::test_health_activates_stage377_and_migration_51",
  "tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py::test_health_activates_stage378_and_migration_52",
  "tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py::test_01_health_activates_stage379_migration53_and_durable_store",
  "tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py::test_01_health_activates_stage3710_closure_without_new_migration",
  "tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py::test_01_health_activates_stage381_without_database_change",
  "tests/test_stage3_8_3_global_causal_lineage_graph.py::test_health_activates_stage383_without_migration",
  "tests/test_stage3_8_4_live_mission_state_execution_projection.py::test_health_activates_stage384_without_migration"
)

& python -m pytest -q @tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] regression rebase sentinel suite failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] regression rebase sentinel suite"

Write-Host "=============================================================================="
Write-Host "STAGE 3.8.4 HOTFIX 1 REGRESSION REBASE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Run .\STAGE3_8_4_ACCEPTANCE.ps1 next for authoritative full regression closure."
