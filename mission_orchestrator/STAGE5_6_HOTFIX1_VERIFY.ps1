$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=============================================================================="
Write-Host "Stage 5.6 HOTFIX1 - Windows HTTP Regression Stability"
Write-Host "=============================================================================="

Write-Host "`n[1] Python compilation"
python -m compileall -q pentest_subsystem tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[2] Previously failing HTTP 409 pair"
python -m pytest -q `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py::test_10_execution_intake_remains_fail_closed_at_stage410 `
  tests/test_stage5_6_exploitation_agent.py::test_24_http_execution_dispatch_is_rejected_by_stage56
if ($LASTEXITCODE -ne 0) { throw "Previously failing HTTP pair failed" }

Write-Host "`n[3] Stage 4.10 + Stage 5.6 modules"
python -m pytest -q `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.10 + Stage 5.6 regression failed" }

Write-Host "`n[4] Focused Stage 5.6"
python -m pytest -q tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Focused Stage 5.6 failed" }

Write-Host "`n[5] Critical global/Pentest acceptance chain"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage4_10_pentest_foundation_acceptance_gate.py `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_5_attack_path_planning_agent.py `
  tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Critical Stage 3.9.10 -> Stage 5.6 regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 5.6 HOTFIX1 verification"
Write-Host "Now run .\STAGE5_6_ACCEPTANCE.ps1 for the final 1957-test acceptance authority."
Write-Host "=============================================================================="
