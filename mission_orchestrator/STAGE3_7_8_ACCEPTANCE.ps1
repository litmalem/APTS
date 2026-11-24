param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"
function Fail([string]$Message){ Write-Host "[FAIL] $Message" -ForegroundColor Red; Write-Host "`n=============================================================================="; Write-Host "STAGE 3.7.8 ACCEPTANCE: FAIL" -ForegroundColor Red; Write-Host "=============================================================================="; exit 1 }
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }
function Assert-FalseField($Object,[string]$Field){ if($Object.$Field -ne $false){ Fail "$Field must be false" } }
function Assert-TrueField($Object,[string]$Field){ if($Object.$Field -ne $true){ Fail "$Field must be true" } }

$expectedControl="stage3.7.8-atomic-replan-commit-supersession-handoff"
$expectedPrior="stage3.7.7-authoritative-replan-commit-authorization-successor-plan-materialization"
$expectedMigrationLevel=52
$expectedTestCount=1322
$expectedFocusedCount=18
$expectedPredecessorFocusedCount=22
$expectedStageSchema="apts-atomic-replan-commit-supersession-handoff-v1"
$expectedContractSchema="apts-replan-supersession-handoff-contract-v1"
$expectedPrefix="rphof-"
$expectedEvent="MISSION_REPLAN_HANDOFF_READY"
$expectedStatus="HANDOFF_READY"
$expectedStore="mission_replan_handoffs"
$expectedNext="STAGE3_4_ROUTING_THEN_STAGE3_5_DISPATCH"

Write-Host "=============================================================================="
Write-Host "Stage 3.7.8 - Atomic Replan Commit, Supersession & Handoff"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health=Invoke-RestMethod -Method Get -Uri "$MissionBaseUrl/health" } catch { Fail "Mission Orchestrator health endpoint unavailable: $($_.Exception.Message)" }
if($health.status -ne "ok"){ Fail "health.status must be ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.7.8 runtime control is not active" }
if([int]$health.mission_repository_migration_level -ne $expectedMigrationLevel){ Fail "repository migration level must be 52" }
if([int]$health.replan_commit_database_migration_level -ne 51){ Fail "Stage-3.7.7 migration metadata must remain 51" }
if([int]$health.replan_handoff_database_migration_level -ne 52){ Fail "Stage-3.7.8 migration metadata must be 52" }
if($health.replan_handoff_stage_schema_version -ne $expectedStageSchema){ Fail "unexpected Stage-3.7.8 stage schema" }
if($health.replan_handoff_contract_schema_version -ne $expectedContractSchema){ Fail "unexpected Stage-3.7.8 contract schema" }
if($health.replan_handoff_identity_prefix -ne $expectedPrefix){ Fail "handoff identity prefix must be rphof-" }
if($health.replan_handoff_event_type -ne $expectedEvent){ Fail "unexpected handoff event" }
if($health.replan_handoff_status -ne $expectedStatus){ Fail "unexpected handoff status" }
if($health.replan_handoff_persistence_store -ne $expectedStore){ Fail "unexpected handoff store" }
if($health.replan_handoff_next_control -ne $expectedNext){ Fail "unexpected downstream handoff control" }
$supported=@($health.supported_controls)
if($supported.Count -lt 2 -or $supported[-2] -ne $expectedPrior -or $supported[-1] -ne $expectedControl){ Fail "supported-control tail must end with Stage 3.7.7 -> Stage 3.7.8" }
Pass "Stage 3.7.8 runtime, migration, predecessor lineage, and handoff identity are active"

Write-Host "`n[1] Atomic supersession / handoff authority proof"
foreach($field in @(
    "replan_handoff_requires_stage377_committed_successor",
    "replan_handoff_requires_exact_active_successor_head",
    "replan_handoff_atomic_commit_verified",
    "replan_handoff_plan_supersession_verified"
)){ Assert-TrueField $health $field }
foreach($field in @(
    "replan_handoff_cancellation_io_performed",
    "replan_handoff_mission_state_transition_performed",
    "replan_handoff_routing_performed",
    "replan_handoff_delegation_performed",
    "replan_handoff_dispatch_performed",
    "replan_handoff_execution_attempt_created",
    "replan_handoff_target_action_dispatch_performed",
    "replan_handoff_target_actuation"
)){ Assert-FalseField $health $field }
if($health.replan_handoff_effective_episode_state -ne "HANDOFF_READY"){ Fail "effective episode state must be HANDOFF_READY" }
$dispositions=@($health.replan_handoff_supported_task_dispositions)
foreach($d in @("KEEP","DRAIN","CANCEL","SUPERSEDE","REPLACE")){ if($dispositions -notcontains $d){ Fail "missing task disposition $d" } }
Pass "Stage 3.7.8 verifies commit/supersession and declares handoff without cancellation I/O, routing, dispatch, or actuation"

Write-Host "`n[2] Python compile"
& python -m compileall -q mission_orchestrator tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[3] Canonical pytest inventory"
$collect=(& python -m pytest --collect-only -q 2>&1 | Out-String)
if($LASTEXITCODE -ne 0){ Write-Host $collect; Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTestCount tests collected"){ Write-Host $collect; Fail "canonical regression inventory must contain exactly $expectedTestCount tests" }
Pass "Canonical regression inventory contains exactly $expectedTestCount tests"

Write-Host "`n[4] Full Stage 3.1-3.7.8 regression"
& python -m pytest -q
if($LASTEXITCODE -ne 0){ Fail "full Stage 3.1-3.7.8 regression failed" }
Pass "Full Stage 3.1-3.7.8 regression passed"

Write-Host "`n[5] Focused Stage 3.7.8 proof"
$focused=(& python -m pytest -q tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.8 tests failed" }
if($focused -notmatch "(?m)^$expectedFocusedCount passed"){ Fail "focused Stage-3.7.8 suite must report exactly $expectedFocusedCount passed" }
Pass "Focused Stage-3.7.8 proof passed"

Write-Host "`n[6] Stage 3.7.7 predecessor non-regression proof"
$prior=(& python -m pytest -q tests/test_stage3_7_7_authoritative_replan_commit_authorization_successor_plan_materialization.py 2>&1 | Out-String)
Write-Host $prior.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage-3.7.7 predecessor tests failed" }
if($prior -notmatch "(?m)^$expectedPredecessorFocusedCount passed"){ Fail "focused Stage-3.7.7 suite must report exactly $expectedPredecessorFocusedCount passed" }
Pass "Stage-3.7.7 predecessor proof passed"

Write-Host "`n[7] Source/migration presence"
foreach($path in @(
    "mission_orchestrator/replan_handoff.py",
    "migrations/052_stage3_7_8_atomic_replan_commit_supersession_handoff.sql",
    "tests/test_stage3_7_8_atomic_replan_commit_supersession_handoff.py"
)){ if(-not(Test-Path $path)){ Fail "missing $path" } }
$migration=Get-Content "migrations/052_stage3_7_8_atomic_replan_commit_supersession_handoff.sql" -Raw
if($migration -notmatch "mission_replan_handoffs"){ Fail "migration 052 must create mission_replan_handoffs" }
$source=Get-Content "mission_orchestrator/replan_handoff.py" -Raw
if($source -notmatch 'REPLAN_HANDOFF_ID_PREFIX = "rphof-"'){ Fail "rphof identity definition missing" }
if($source -notmatch 'REPLAN_HANDOFF_EVENT_TYPE = "MISSION_REPLAN_HANDOFF_READY"'){ Fail "handoff event definition missing" }
if($source -notmatch '"next_stage": "3.7.9"'){ Fail "Stage 3.7.9 boundary missing" }
Pass "Stage-3.7.8 source and migration proof passed"

Write-Host "`n=============================================================================="
Write-Host "STAGE 3.7.8 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "=============================================================================="
