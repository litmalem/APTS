$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 3.8.10 Hotfix 1 - Supported-Control Regression Rebase Verification"
Write-Host "=============================================================================="

& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Python compilation failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] Python compilation"

$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1431 tests collected') {
    Write-Host "[FAIL] canonical inventory must contain 1431 tests" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] 1431 tests collected"

$tests = @(
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_health_declares_stage34_closure_without_new_authority_or_migration",
  "tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py::test_stage3410_final_supported_control_tail_is_complete_and_ordered",
  "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed",
  "tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py"
)

& python -m pytest -q @tests
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] Stage 3.8.10 Hotfix 1 sentinel suite failed" -ForegroundColor Red
    exit 1
}
Write-Host "[PASS] Stage 3.8.10 Hotfix 1 sentinel suite"

Write-Host "=============================================================================="
Write-Host "STAGE 3.8.10 HOTFIX 1 REGRESSION REBASE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
Write-Host "Next: rerun .\STAGE3_8_10_ACCEPTANCE.ps1 for authoritative full regression closure."
