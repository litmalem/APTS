$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

Write-Host "=============================================================================="
Write-Host "Stage 3.9.10 - Global Mission Orchestrator Acceptance & Regression Gate"
Write-Host "=============================================================================="

$ExpectedControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedMigration = 53
$ExpectedInventory = 1575
$ExpectedSchema = "apts-stage3.9-global-mission-orchestrator-acceptance-regression-gate-v1"
$ExpectedPredecessor = "stage3.9.9-global-observation-reconstruction-forensic-equivalence"
$ExpectedOutput = "GLOBAL_MISSION_ORCHESTRATOR"
$ExpectedNextStage = "4.1"
$Url = if ($env:MISSION_ORCHESTRATOR_URL) { $env:MISSION_ORCHESTRATOR_URL.TrimEnd('/') } else { "http://127.0.0.1:8780" }
$env:PYTHONPATH = (Get-Location).Path + ";" + (Join-Path (Get-Location).Path "tests")

Write-Host "`n[0] Runtime activation preflight"
$healthWeb = Invoke-WebRequest "$Url/health" -UseBasicParsing
$ObservedServer = $healthWeb.Headers["Server"]
if ($ObservedServer -notmatch "APTSMissionOrchestrator/3\.9\.10") { throw "server version mismatch: $ObservedServer" }
$health = $healthWeb.Content | ConvertFrom-Json
if ($health.control_version -ne $ExpectedControl) { throw "control_version mismatch: $($health.control_version)" }
if ([int]$health.mission_repository_migration_level -ne $ExpectedMigration) { throw "migration mismatch" }
if ($health.stage3_9_10_global_mission_acceptance_gate_schema_version -ne $ExpectedSchema) { throw "Stage 3.9.10 schema inactive" }
if ($health.stage3_9_10_predecessor_control -ne $ExpectedPredecessor) { throw "predecessor health mismatch" }
if ([int]$health.stage3_9_10_expected_repository_migration_level -ne $ExpectedMigration) { throw "expected migration mismatch" }
if (-not $health.stage3_9_10_declared_only) { throw "closure gate must be declared-only" }
if ($health.stage3_9_10_runtime_self_certification) { throw "runtime self-certification must remain disabled" }
if (-not $health.stage3_9_10_external_acceptance_execution_required) { throw "external acceptance execution is not required" }
if (-not $health.stage3_9_10_full_historical_regression_required) { throw "full historical regression is not required" }
if (@($health.stage3_9_10_required_stage3_9_controls).Count -ne 9) { throw "Stage 3.9 prior-control count mismatch" }
if ($health.stage3_9_10_required_stage3_9_controls[-1] -ne $ExpectedPredecessor) { throw "Stage 3.9 predecessor ordering mismatch" }
if ($health.stage3_9_10_new_database_migration_added -or $health.stage3_9_10_new_durable_store_added) { throw "unexpected persistence expansion" }
if ($health.stage3_9_10_new_execution_authority_added -or $health.stage3_9_10_new_governance_authority_added -or $health.stage3_9_10_new_routing_authority_added -or $health.stage3_9_10_new_delegation_authority_added -or $health.stage3_9_10_new_dispatch_authority_added -or $health.stage3_9_10_new_recovery_authority_added -or $health.stage3_9_10_new_observation_authority_added -or $health.stage3_9_10_new_forensic_authority_added) { throw "unexpected Stage 3.9.10 authority expansion" }
if ($health.stage3_9_10_telemetry_export_performed -or $health.stage3_9_10_external_network_io_performed -or $health.stage3_9_10_target_actuation) { throw "unexpected Stage 3.9.10 I/O/actuation" }
if ($health.stage3_9_10_stage_output -ne $ExpectedOutput) { throw "Stage 3 output mismatch" }
if ($health.stage3_9_10_next_stage -ne $ExpectedNextStage) { throw "next-stage health mismatch" }
Write-Host "[PASS] runtime contract active"

Write-Host "`n[1] Final gate contract API"
$gate = Invoke-RestMethod "$Url/api/e2e/global-mission-orchestrator-acceptance-regression-gate-contract"
if ($gate.control_version -ne $ExpectedControl) { throw "contract route control mismatch" }
if ($gate.definition.schema_version -ne $ExpectedSchema) { throw "contract schema mismatch" }
if ($gate.definition.predecessor_control -ne $ExpectedPredecessor) { throw "contract predecessor mismatch" }
if ([int]$gate.definition.expected_repository_migration_level -ne $ExpectedMigration) { throw "contract migration mismatch" }
if ([int]$gate.definition.required_stage_domain_closure_control_count -ne 8) { throw "Stage-domain closure-control count mismatch" }
if ([int]$gate.definition.required_stage3_9_control_count -ne 9) { throw "Stage 3.9 control count mismatch" }
if (-not $gate.definition.declared_only) { throw "contract is not declared-only" }
if ($gate.definition.runtime_self_certification) { throw "contract incorrectly allows runtime self-certification" }
if (-not $gate.definition.external_acceptance_execution_required) { throw "contract does not require external acceptance" }
if (-not $gate.definition.full_historical_regression_required) { throw "contract does not require full historical regression" }
if ($gate.definition.new_database_migration_added -or $gate.definition.new_durable_store_added -or $gate.definition.new_runtime_authority_added -or $gate.definition.target_actuation) { throw "contract boundary expansion detected" }
if ($gate.definition.stage_output -ne $ExpectedOutput) { throw "contract Stage 3 output mismatch" }
if ($gate.definition.next_stage -ne $ExpectedNextStage) { throw "contract next-stage mismatch" }
if (-not $gate.read_only) { throw "contract route must be read-only" }
if ($gate.runtime_self_certification) { throw "route incorrectly self-certifies" }
Write-Host "[PASS] Stage 3.9.10 contract route"

Write-Host "`n[2] Python compilation"
python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[3] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[4] Focused Stage 3.9.10"
python -m pytest -q tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9.10 focused regression failed" }

Write-Host "`n[5] Stage 3.9 canonical E2E qualification chain"
python -m pytest -q `
  tests/test_stage3_9_1_canonical_e2e_mission_scenario_acceptance_contract.py `
  tests/test_stage3_9_2_intake_lifecycle_e2e_segment_qualification.py `
  tests/test_stage3_9_3_planning_task_graph_dependency_verification.py `
  tests/test_stage3_9_4_routing_delegation_governance_continuity.py `
  tests/test_stage3_9_5_dispatch_execution_evidence_continuity.py `
  tests/test_stage3_9_6_task_completion_mission_outcome_closure.py `
  tests/test_stage3_9_7_adaptation_replanning_e2e_scenario.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py `
  tests/test_stage3_9_9_global_observation_reconstruction_forensic_equivalence.py `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage 3.9 E2E qualification chain failed" }

Write-Host "`n[6] Stage-domain closure gate regression"
python -m pytest -q `
  tests/test_stage3_1_10_acceptance_regression_gate.py `
  tests/test_stage3_2_10_lifecycle_acceptance_regression_gate.py `
  tests/test_stage3_3_10_planning_acceptance_regression_gate.py `
  tests/test_stage3_4_10_routing_delegation_acceptance_regression_gate.py `
  tests/test_stage3_5_10_execution_dispatch_acceptance_regression_gate.py `
  tests/test_stage3_6_10_outcome_acceptance_regression_gate.py `
  tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py `
  tests/test_stage3_8_10_observe_reconstruct_acceptance_regression_gate.py `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "Stage-domain closure regression failed" }

Write-Host "`n[7] Global lineage / governance / recovery / forensic critical regression"
python -m pytest -q `
  tests/test_stage3_5_3_authoritative_pre_dispatch_governance_revalidation.py `
  tests/test_stage3_5_4_idempotent_dispatch_execution_attempt_identity.py `
  tests/test_stage3_6_3_evidence_binding_verification.py `
  tests/test_stage3_6_9_outcome_lineage_replay_recovery.py `
  tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py `
  tests/test_stage3_7_9_adapt_replan_lineage_replay_recovery.py `
  tests/test_stage3_8_7_integrity_gap_consistency_diagnostics.py `
  tests/test_stage3_8_9_forensic_query_evidence_bundle_reconstruction_api.py `
  tests/test_stage3_9_8_restart_replay_recovery_e2e_verification.py `
  tests/test_stage3_9_9_global_observation_reconstruction_forensic_equivalence.py `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py
if ($LASTEXITCODE -ne 0) { throw "critical global regression failed" }

Write-Host "`n[8] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 3.9.10 Global Mission Orchestrator Acceptance & Regression Gate"
Write-Host "control_version : $ExpectedControl"
Write-Host "migration       : $ExpectedMigration"
Write-Host "inventory       : $ExpectedInventory"
Write-Host "predecessor     : Stage 3.9.9 QUALIFIED / global equivalence PASS"
Write-Host "gate authority  : external acceptance harness; runtime self-certification disabled"
Write-Host "boundary        : no new persistence / runtime authority / external I/O / target actuation"
Write-Host "STAGE 3 OUTPUT  : GLOBAL MISSION ORCHESTRATOR"
Write-Host "next            : Stage 4.1"
Write-Host "=============================================================================="
