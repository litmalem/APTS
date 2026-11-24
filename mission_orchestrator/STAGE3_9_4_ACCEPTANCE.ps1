$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.4 - Routing -> Delegation -> Governance Continuity"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.4-routing-delegation-governance-continuity"
$ExpectedMigration = 53
$ExpectedInventory = 1485
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$health = Invoke-RestMethod "$Url/health"
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_4_routing_delegation_governance_qualification_schema_version -ne "apts-stage3.9-routing-delegation-governance-continuity-v1") { throw "Stage 3.9.4 schema inactive" }
if (-not $health.stage3_9_4_runtime_verifier_read_only) { throw "Stage 3.9.4 verifier is not read-only" }
if (-not $health.stage3_9_4_authoritative_governance_required) { throw "authoritative governance requirement inactive" }
if (-not $health.stage3_9_4_pre_dispatch_governance_revalidation_required) { throw "pre-dispatch revalidation requirement inactive" }
if ($health.stage3_9_4_new_database_migration_added) { throw "unexpected Stage 3.9.4 migration" }
if ($health.stage3_9_4_new_dispatch_authority_added) { throw "unexpected Stage 3.9.4 dispatch authority" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Contract API"
$contract = Invoke-RestMethod "$Url/api/e2e/routing-delegation-governance-qualification-contract"
if ($contract.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($contract.definition.next_stage -ne "3.9.5") { throw "next-stage mismatch" }
Write-Host "[PASS] Stage 3.9.4 contract route"

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

Write-Host "`n[4] Focused Stage 3.9.4"
pytest -q tests/test_stage3_9_4_routing_delegation_governance_continuity.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.4 focused regression failed" }

Write-Host "`n[5] Stage 3.9 E2E predecessor chain"
pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 chain regression failed" }

Write-Host "`n[6] Planning-to-routing/delegation authority regression"
pytest -q `
  tests/test_stage3_3_5_planner_invocation_plan_generation.py `
  tests/test_stage3_3_6_plan_validation_feasibility_gate.py `
  tests/test_stage3_3_7_plan_versioning_replanning_supersession.py `
  tests/test_stage3_3_8_task_readiness_scheduling_projection.py `
  tests/test_stage3_4_2_task_routing_intent_candidate_resolution.py `
  tests/test_stage3_4_3_routing_eligibility_compatibility_gate.py `
  tests/test_stage3_4_4_deterministic_route_selection_decision_record.py `
  tests/test_stage3_4_5_governance_bound_delegation_authorization.py `
  tests/test_stage3_4_6_canonical_delegation_contract_handoff_envelope.py `
  tests/test_stage3_4_7_delegation_delivery_acknowledgement_ownership.py
if ($LASTEXITCODE -ne 0) { throw "planning/routing/delegation regression failed" }

Write-Host "`n[7] Full regression"
pytest -q
if ($LASTEXITCODE -ne 0) { throw "full regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.4 Routing -> Delegation -> Governance Continuity"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "next            : Stage 3.9.5 - Dispatch -> Execution -> Evidence"
Write-Host "=============================================================================="
