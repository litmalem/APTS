$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.10 Hotfix 1 - Historical Regression Compatibility"
Write-Host "=============================================================================="

$expected = "assert controls[-21:] == ["
$testFile = Join-Path $PSScriptRoot "tests\test_stage3_8_1_canonical_observability_trace_identity_contract.py"

if (-not (Test-Path $testFile)) {
    throw "missing historical regression file: $testFile"
}

$content = Get-Content -Raw $testFile
if (-not $content.Contains($expected)) {
    throw "hotfix marker not found: expected controls[-21:] suffix assertion"
}
Write-Host "[PASS] hotfix marker present"

python -m pytest -q `
    tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py `
    tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) {
    throw "hotfix regression verification failed"
}

Write-Host "[PASS] Stage 3.9.10 Hotfix 1 regression compatibility"
