param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.7.7 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization"
$expectedPrior="stage3.7.6-replan-candidate-validation-delta-feasibility-gate"
$expectedMigrationLevel=51
$expectedTestCount=1304
$expectedFocusedCount=22
$expectedStageSchema="apts-authoritative-replan-commit-authorization-successor-plan-materialization-v1"
$expectedContractSchema="apts-authoritative-replan-commit-contract-v1"
$expectedPrefix="rpcom-"
$expectedEvent="MISSION_REPLAN_COMMIT_AUTHORIZED_SUCCESSOR_PLAN_MATERIALIZED"
$expectedStatus="COMMITTED_SUCCESSOR_PLAN"
$expectedStore="mission_replan_commits"
$expectedActionClass="INTERNAL_REASONING"
$expectedActionName="AUTHORIZE_REPLAN_COMMIT"
$expectedResource="MISSION"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.7 - Authoritative Replan Commit Authorization & Successor Plan Materialization"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.7 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be 51" }
if([int]$health.replan_validation_database_migration_level -ne 50){ Fail "Stage-3.7.6 migration metadata must remain 50" }
if([int]$health.replan_commit_database_migration_level -ne 51){ Fail "Stage-3.7.7 migration metadata must be 51" }
if($health.replan_commit_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.7 stage schema" }
if($health.replan_commit_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.7 contract schema" }
if($health.replan_commit_identity_prefix -ne $expectedPrefix){ Fail "commit identity prefix must be rpcom-" }
if($health.replan_commit_event_type -ne $expectedEvent){ Fail "unexpected commit event" }
if($health.replan_commit_status -ne $expectedStatus){ Fail "unexpected commit status" }
if($health.replan_commit_persistence_store -ne $expectedStore){ Fail "unexpected commit store" }
if($health.replan_commit_governance_action_class -ne $expectedActionClass){ Fail "unexpected Governance action class" }
if($health.replan_commit_governance_action_name -ne $expectedActionName){ Fail "unexpected Governance action name" }
if($health.replan_commit_governance_resource_type -ne $expectedResource){ Fail "unexpected Governance resource type" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPrior -or $supported[-1] -ne $expectedControl){ Fail "supported-control tail must end with Stage 3.7.6 -> Stage 3.7.7" }
Pass "Stage 3.7.7 runtime, migration, predecessor lineage, Governance identity, and persistence identity are active"

Write-Host "`n[1] Commit authority and fail-closed boundary proof"
foreach($field in @(
    "replan_commit_requires_stage376_validated_for_commit",
    "replan_commit_requires_exact_stage375_candidate",
    "replan_commit_requires_exact_stage374_snapshot",
    "replan_commit_authoritative_governance_revalidation_performed",
    "replan_commit_atomic_successor_plan_materialization",
    "replan_commit_active_head_cas",
    "replan_commit_replan_decision_committed",
    "replan_commit_successor_plan_created",
    "replan_commit_plan_supersession_performed"
)){ Assert-TrueField $health $field }
foreach($field in @(
    "replan_commit_historical_plan_mutation_performed",
    "replan_commit_mission_state_transition_performed",
    "replan_commit_routing_performed",
    "replan_commit_delegation_performed",
    "replan_commit_dispatch_performed",
    "replan_commit_execution_attempt_created",
    "replan_commit_target_action_dispatch_performed",
    "replan_commit_target_actuation"
)){ Assert-FalseField $health $field }
Pass "Stage 3.7.7 has commit/successor-head authority but no lifecycle/routing/dispatch/actuation authority"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.7 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.7 regression failed" }
Pass "Full Stage 3.1-3.7.7 regression passed"

Write-Host "`n[5] Focused Stage 3.7.7 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.7 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.7 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.7 proof passed"

Write-Host "`n[6] Source/migration presence"
foreach($path in @(
    "mission_orchestrator/replan_commit.py",
    "migrations/051_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.sql",
    "tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py"
)){ if(-not(Test-Path $path)){ Fail "missing $path" } }
$migration=Get-Content "migrations/051_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.sql" -Raw
if($migration -notmatch "mission_replan_commits"){ Fail "migration 051 must create mission_replan_commits" }
$source=Get-Content "mission_orchestrator/replan_commit.py" -Raw
if($source -notmatch 'REPLAN_COMMIT_ID_PREFIX = "rpcom-"'){ Fail "rpcom identity definition missing" }
if($source -notmatch 'REPLAN_COMMIT_GOVERNANCE_ACTION_NAME = "AUTHORIZE_REPLAN_COMMIT"'){ Fail "authoritative Governance action definition missing" }
if($source -notmatch '"next_stage": "3.7.8"'){ Fail "Stage 3.7.8 boundary missing" }
Pass "Stage-3.7.7 source and migration proof passed"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.7 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
