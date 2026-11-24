$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 3.8.1 - Regression Rebase Hotfix 2 Verification"
Write-Host "=============================================================================="

$tests = @(
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_health_declares_stage34_closure_without_new_authority_or_migration",
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered",
  "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed",
  "tests/test_stage3_6_10_outcome_acceptance_regression_gate.py::test_01_health_activates_stage3610_closure_without_new_migration",
  "tests/test_stage3_7_1_canonical_adaptation_replan_contract_identity.py::test_health_activates_stage371_contract_identity_and_migration_45",
  "tests/test_stage3_7_2_adaptation_trigger_detection_classification.py::test_health_activates_stage372_classification_and_migration_46",
  "tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py::test_health_activates_stage377_and_migration_51",
  "tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py::test_health_activates_stage378_and_migration_52",
  "tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py::test_01_health_activates_stage379_migration53_and_durable_store"
)

Write-Host "[1] Re-running the 9 previously failing regression assertions"
& python -m pytest -q @tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Hotfix 2 regression rebase verification failed"
    exit 1
}
Write-Host "[PASS] 9/9 previous regression failures are repaired"

Write-Host ""
Write-Host "[2] Stage 3.7.10 predecessor focused suite"
& python -m pytest -q tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Stage 3.7.10 predecessor focused suite failed"
    exit 1
}
Write-Host "[PASS] Stage 3.7.10 predecessor focused suite passed"

Write-Host ""
Write-Host "[3] Stage 3.8.1 focused suite"
& python -m pytest -q tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Stage 3.8.1 focused suite failed"
    exit 1
}
Write-Host "[PASS] Stage 3.8.1 focused suite passed"

Write-Host ""
Write-Host "=============================================================================="
Write-Host "STAGE 3.8.1 REGRESSION REBASE HOTFIX 2: PASS"
Write-Host "=============================================================================="
Write-Host "Run .\STAGE3_8_1_ACCEPTANCE.ps1 next for authoritative full regression closure."
