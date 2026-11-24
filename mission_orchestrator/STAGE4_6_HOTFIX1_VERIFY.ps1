$ErrorActionPreference = "Stop"

Write-Host "=============================================================================="
Write-Host "Stage 4.6 HOTFIX1 - Windows Local HTTP Regression Stability"
Write-Host "=============================================================================="

Write-Host "`n[1] Python compilation"
python -m compileall -q pentest_subsystem tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[2] Focused Stage 4.6"
python -m pytest -q tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py
if ($LASTEXITCODE -ne 0) { throw "Focused Stage 4.6 failed" }

Write-Host "`n[3] Stage 4.1 -> 4.6 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.6 regression failed" }

Write-Host "`n[4] Critical Stage 3 + Stage 4 predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py
if ($LASTEXITCODE -ne 0) { throw "Critical predecessor regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.6 HOTFIX1 verification"
Write-Host "Now run .\STAGE4_6_ACCEPTANCE.ps1 for the final 1697-test acceptance authority."
Write-Host "=============================================================================="
