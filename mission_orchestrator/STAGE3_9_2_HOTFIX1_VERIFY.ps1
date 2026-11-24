$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.2 Hotfix 1 - Supported-Control Regression Rebase Verification"
Write-Host "=============================================================================="

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python compilation failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] Python compilation"

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1458 tests collected') {
    Write-Host "[FAIL] canonical inventory must contain 1458 tests" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] 1458 tests collected"

$failedTests = @(
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered",
  "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed",
  "tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py::test_12_stage3710_remains_immediate_predecessor_in_supported_control_chain"
)

Write-Host ""
Write-Host "[1] Re-running the 3 previously failing assertions"
& python -m pytest -q @failedTests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] previously failing assertions are not repaired" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] 3/3 previous regression failures are repaired"

$modules = @(
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py",
  "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py",
  "tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py",
  "tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py",
  "tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py"
)

Write-Host ""
Write-Host "[2] Affected + Stage 3.9 predecessor/current module set"
& python -m pytest -q @modules
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Stage 3.9.2 Hotfix 1 sentinel module set failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] Stage 3.9.2 Hotfix 1 sentinel module set"

Write-Host ""
Write-Host "=============================================================================="
Write-Host "STAGE 3.9.2 HOTFIX 1 REGRESSION REBASE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Next: rerun .\STAGE3_9_2_ACCEPTANCE.ps1 for authoritative full regression closure."
