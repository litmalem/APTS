$ErrorActionPreference = "Stop"

$compileFiles = @(
  ".\execution_subsystem\execution_contract.py",
  ".\execution_subsystem\proposal_source.py",
  ".\execution_subsystem\authorization_source.py",
  ".\execution_subsystem\authorization_contract.py",
  ".\execution_subsystem\gateway_service.py",
  ".\execution_subsystem\tool_registry.py",
  ".\execution_subsystem\adapter_repository.py",
  ".\execution_subsystem\runtime_repository.py",
  ".\execution_subsystem\evidence_contract.py",
  ".\execution_subsystem\evidence_repository.py",
  ".\execution_subsystem\execution_result_contract.py",
  ".\execution_subsystem\evidence_service.py",
  ".\execution_subsystem\evidence_api.py",
  ".\execution_subsystem\vep_source.py",
  ".\pentest_subsystem\enumeration.py",
  ".\pentest_subsystem\api_service.py",
  ".\tests\test_stage13_enumeration_stage6_e2e.py"
)
python -m py_compile @compileFiles
if ($LASTEXITCODE -ne 0) { throw "Stage 13 Python compilation failed" }

$tests = @(
  ".\tests\test_stage4_8_governance_scope_roe_enforcement.py",
  ".\tests\test_stage5_3_enumeration_agent.py",
  ".\tests\test_stage6_1_canonical_execution_request_contract.py",
  ".\tests\test_stage6_2_authoritative_execution_authorization.py",
  ".\tests\test_stage6_3_controlled_execution_gateway.py",
  ".\tests\test_stage6_3_4_recon_gateway_capability.py",
  ".\tests\test_stage6_4_authorized_tool_adapters_sandboxing.py",
  ".\tests\test_stage6_5_execution_runtime_control.py",
  ".\tests\test_stage6_6_artifact_evidence_capture.py",
  ".\tests\test_stage12_recon_active_e2e_acceptance.py",
  ".\tests\test_stage13_enumeration_stage6_e2e.py"
)
python -m pytest -q @tests
if ($LASTEXITCODE -ne 0) { throw "Stage 13 acceptance/regression suite failed" }
Write-Host "Stage 13 acceptance and related regressions passed."
