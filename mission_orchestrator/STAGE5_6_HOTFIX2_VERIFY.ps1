$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=============================================================================="
Write-Host "Stage 5.6 HOTFIX2 - Windows HTTP Regression Propagation"
Write-Host "=============================================================================="

Write-Host "`n[1] Python compilation"
python -m compileall -q pentest_subsystem tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[2] Previously failing Stage 5.2 / Stage 5.5 HTTP 409 pair"
python -m pytest -q `
  tests/test_stage5_2_reconnaissance_agent.py::test_21_http_execution_dispatch_remains_rejected_for_stage52 `
  tests/test_stage5_5_attack_path_planning_agent.py::test_24_http_execution_dispatch_remains_rejected_for_stage55
if ($LASTEXITCODE -ne 0) { throw "Previously failing Stage 5.2 / Stage 5.5 HTTP pair failed" }

Write-Host "`n[3] Patched Stage 5.1 -> Stage 5.5 predecessor HTTP modules"
python -m pytest -q `
  tests/test_stage5_1_full_agentic_pentest_workflow_orchestrator.py `
  tests/test_stage5_2_reconnaissance_agent.py `
  tests/test_stage5_3_enumeration_agent.py `
  tests/test_stage5_4_vulnerability_hypothesis_agent.py `
  tests/test_stage5_5_attack_path_planning_agent.py
if ($LASTEXITCODE -ne 0) { throw "Patched Stage 5.1 -> Stage 5.5 regression failed" }

Write-Host "`n[4] Focused Stage 5.6"
python -m pytest -q tests/test_stage5_6_exploitation_agent.py
if ($LASTEXITCODE -ne 0) { throw "Focused Stage 5.6 failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 5.6 HOTFIX2 verification"
Write-Host "Now run .\STAGE5_6_ACCEPTANCE.ps1 for the authoritative 1957-test acceptance."
Write-Host "=============================================================================="
