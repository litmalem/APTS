$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.5 - Dispatch -> Execution -> Evidence Continuity"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.5-dispatch-execution-evidence-continuity"
$ExpectedMigration = 53
$ExpectedInventory = 1500
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_5_dispatch_execution_evidence_schema_version -ne "apts-stage3.9-dispatch-execution-evidence-continuity-v1") { throw "Stage 3.9.5 schema inactive" }
if (-not $health.stage3_9_5_runtime_verifier_read_only) { throw "Stage 3.9.5 verifier is not read-only" }
if (-not $health.stage3_9_5_authoritative_pre_dispatch_governance_allow_required) { throw "pre-dispatch Governance requirement inactive" }
if ($health.stage3_9_5_execution_result_is_task_completion) { throw "execution/completion boundary violated" }
if ($health.stage3_9_5_new_database_migration_added -or $health.stage3_9_5_new_durable_store_added) { throw "unexpected Stage 3.9.5 persistence expansion" }
if ($health.stage3_9_5_new_governance_authority_added -or $health.stage3_9_5_new_dispatch_authority_added -or $health.stage3_9_5_new_execution_authority_added) { throw "unexpected Stage 3.9.5 authority expansion" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/dispatch-execution-evidence-qualification-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.predecessor_control -ne "stage3.9.4-routing-delegation-governance-continuity") { throw "predecessor mismatch" }
if ($contract.definition.next_stage -ne "3.9.6") { throw "next-stage mismatch" }
Write-Host "[PASS] Stage 3.9.5 contract route"

Write-Host "`n[2] Python compilation"
python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[3] Canonical test inventory"
$collect = pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[4] Focused Stage 3.9.5"
pytest -q tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.5 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E predecessor chain"
pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Dispatch / runtime / evidence authority regression"
pytest -q `
  tests/test_stage3_5_1_canonical_execution_dispatch_contract_identity.py `
  tests/test_stage3_5_2_dispatch_eligibility_execution_preconditions.py `
  tests/test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.py `
  tests/test_stage3_5_4_idempotent_dispatch_execution_attempt_identity.py `
  tests/test_stage3_5_5_dispatch_delivery_execution_acknowledgement.py `
  tests/test_stage3_5_6_running_execution_state_heartbeat_projection.py `
  tests/test_stage3_5_7_execution_result_evidence_artifact_capture.py `
  tests/test_stage3_5_8_timeout_cancellation_abort_failure_propagation.py `
  tests/test_stage3_5_9_execution_event_lineage_replay_recovery.py `
  tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.5 execution regression failed" }

Write-Host "`n[7] Full historical regression"
pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.5 Dispatch -> Execution -> Evidence Continuity"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "next            : Stage 3.9.6 - Completion -> Outcome"
Write-Host "=============================================================================="
