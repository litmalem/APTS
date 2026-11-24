$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "=============================================================================="
Write-Host "Stage 3.9.3 Hotfix 2 - Supported-Control Regression Rebase Verification"
Write-Host "=============================================================================="

$files = @(
    "tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py",
    "tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py",
    "tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py",
    "tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py",
    "tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py",
    "tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py",
    "tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py"
)

python -m py_compile @files
if ($LASTEXITCODE -ne 0) { throw "[FAIL] modified-test Python compilation failed" }
Write-Host "[PASS] modified-test Python compilation"

$collection = python -m pytest --collect-only -q 2>&1
if ($LASTEXITCODE -ne 0) {
    $collection | ForEach-Object { Write-Host $_ }
    throw "[FAIL] canonical collection failed"
}
$collectionText = ($collection -join "`n")
if ($collectionText -notmatch "1473 tests collected") {
    $collection | Select-Object -Last 8 | ForEach-Object { Write-Host $_ }
    throw "[FAIL] canonical inventory is not 1473"
}
Write-Host "[PASS] 1473 tests collected"

python -m pytest -q `
    tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py::test_12_stage35_supported_control_tail_is_complete_ordered_and_closed `
    tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py::test_health_activates_closure_without_migration_or_new_authority `
    tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py::test_12_stage3710_remains_immediate_predecessor_in_supported_control_chain `
    tests/test_stage3_8_6_deterministic_mission_timeline_reconstruction.py::test_unknown_mission_and_contract_and_health `
    tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py::test_contract_health_and_unknown_mission `
    tests/test_stage3_8_8_observability_metrics_health_operator_diagnostics.py::test_health_contract_unknown_mission_and_http_routes `
    tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py::test_contract_health_unknown_mission_and_invalid_scope
if ($LASTEXITCODE -ne 0) { throw "[FAIL] exact seven regression-rebase tests failed" }
Write-Host "[PASS] exact seven host-failing tests"

Write-Host "=============================================================================="
Write-Host "STAGE 3.9.3 HOTFIX 2 VERIFY: PASS"
Write-Host "Next: .\STAGE3_9_3_ACCEPTANCE.ps1"
Write-Host "=============================================================================="
