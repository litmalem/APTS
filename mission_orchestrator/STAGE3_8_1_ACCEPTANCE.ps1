param([string]$MissionBaseUrl = "http://127.0.0.1:8780")
$ErrorActionPreference = "Stop"

function Fail([string]$Message){
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    Write-Host "`n==============================================================================" -ForegroundColor Red
    Write-Host "STAGE 3.8.1 ACCEPTANCE: FAIL" -ForegroundColor Red
    Write-Host "==============================================================================" -ForegroundColor Red
    exit 1
}
function Pass([string]$Message){ Write-Host "[PASS] $Message" -ForegroundColor Green }

$expectedControl = "stage3.8.1-canonical-observability-trace-identity-contract"
$expectedTests = 1368
$expectedFocused = 12
$expectedPredecessor = 12

Write-Host "=============================================================================="
Write-Host "Stage 3.8.1 - Canonical Observability & Trace Identity Contract"
Write-Host "=============================================================================="
Write-Host "Mission Orchestrator : $MissionBaseUrl"

Write-Host "`n[0] Runtime activation preflight"
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "health endpoint unavailable: $($_.Exception.Message)" }
Write-Host "      observed control_version : $($health.control_version)"
Write-Host "      expected control_version : $expectedControl"
if($health.status -ne "ok"){ Fail "runtime health status is not ok" }
if($health.control_version -ne $expectedControl){ Fail "Stage 3.8.1 runtime control is not active" }
if($health.mission_repository_migration_level -ne 53){ Fail "repository migration level must remain 53" }
if($health.observability_trace_schema_version -ne "apts-canonical-observability-trace-identity-v1"){ Fail "trace schema mismatch" }
if($health.observability_trace_context_schema_version -ne "apts-observability-trace-context-v1"){ Fail "trace context schema mismatch" }
if($health.observability_trace_database_change_mode -ne "NO_NEW_DATABASE_MIGRATION"){ Fail "Stage 3.8.1 must not add a database migration" }
if($health.observability_trace_new_durable_store_added -ne $false){ Fail "Stage 3.8.1 must not add a durable store" }
if($health.observability_trace_read_only_projection -ne $true){ Fail "trace identity must be read-only" }
if($health.observability_trace_telemetry_export_performed -ne $false){ Fail "telemetry export must remain disabled" }
if($health.observability_trace_external_network_io_performed -ne $false){ Fail "external network I/O must remain disabled" }
if($health.observability_trace_dispatch_performed -ne $false){ Fail "dispatch must remain disabled by Stage 3.8.1" }
if($health.observability_trace_target_actuation -ne $false){ Fail "target actuation must remain disabled by Stage 3.8.1" }
Pass "Stage 3.8.1 runtime control is active with migration level 53"

Write-Host "`n[1] Python compile"
& python -m compileall -q mission_orchestrator run tests
if($LASTEXITCODE -ne 0){ Fail "Python compilation failed" }
Pass "Python compilation passed"

Write-Host "`n[2] Canonical pytest inventory"
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
Write-Host $collect.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "pytest collection failed" }
if($collect -notmatch "(?m)^$expectedTests tests collected"){ Fail "canonical regression inventory must contain exactly $expectedTests tests" }
Pass "Canonical regression inventory contains exactly $expectedTests tests"

Write-Host "`n[3] Full Stage 3.1-3.8.1 regression"
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "full regression failed" }
if($full -notmatch "(?m)^$expectedTests passed"){ Fail "full regression must report exactly $expectedTests passed" }
Pass "Full Stage 3.1-3.8.1 regression passed"

Write-Host "`n[4] Focused Stage 3.8.1 proof"
$focused = (& python -m pytest -q tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "focused Stage 3.8.1 tests failed" }
if($focused -notmatch "(?m)^$expectedFocused passed"){ Fail "focused Stage 3.8.1 suite must report exactly $expectedFocused passed" }
Pass "Focused Stage 3.8.1 proof passed"

Write-Host "`n[5] Stage 3.7.10 predecessor non-regression"
$pred = (& python -m pytest -q tests/test_stage3_7_10_adapt_replan_acceptance_regression_gate.py 2>&1 | Out-String)
Write-Host $pred.TrimEnd()
if($LASTEXITCODE -ne 0){ Fail "Stage 3.7.10 predecessor suite failed" }
if($pred -notmatch "(?m)^$expectedPredecessor passed"){ Fail "Stage 3.7.10 predecessor suite must report exactly $expectedPredecessor passed" }
Pass "Stage 3.7.10 predecessor closure remains intact"

Write-Host "`n[6] Migration / version / source boundary"
foreach($path in @(
    "mission_orchestrator/observability_trace.py",
    "mission_orchestrator/service.py",
    "mission_orchestrator/api_service.py",
    "tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py"
)){ if(-not(Test-Path $path)){ Fail "missing $path" } }
if(Test-Path "migrations/054_stage3_8_1_canonical_observability_trace_identity_contract.sql"){ Fail "Stage 3.8.1 must not add migration 054" }
if((Get-ChildItem "migrations/*.sql").Count -ne 53){ Fail "migration inventory must remain exactly 53 SQL migrations" }
$svc = Get-Content "mission_orchestrator/service.py" -Raw
if($svc -notmatch [regex]::Escape('CONTROL_VERSION = "stage3.8.1-canonical-observability-trace-identity-contract"')){ Fail "service control version mismatch" }
$api = Get-Content "mission_orchestrator/api_service.py" -Raw
if($api -notmatch [regex]::Escape('server_version = "APTSMissionOrchestrator/3.8.1"')){ Fail "API server version mismatch" }
$trace = Get-Content "mission_orchestrator/observability_trace.py" -Raw
foreach($token in @(
    'OBSERVABILITY_TRACE_SCHEMA_VERSION = "apts-canonical-observability-trace-identity-v1"',
    'OBSERVABILITY_TRACE_DATABASE_CHANGE_MODE = "NO_NEW_DATABASE_MIGRATION"',
    'OBSERVABILITY_TRACE_EXPORT_MODE = "DISABLED_STAGE_3_8_1"',
    '"telemetry_export_performed": False',
    '"target_actuation": False'
)){ if($trace -notmatch [regex]::Escape($token)){ Fail "trace source token missing: $token" } }
Pass "Stage 3.8.1 source/version boundary verified"

Write-Host "`n[7] Contract definition endpoint"
try { $definition = Invoke-RestMethod "$MissionBaseUrl/api/observability/trace-contract" } catch { Fail "trace contract endpoint unavailable: $($_.Exception.Message)" }
if($definition.definition.trace_tree_scope -ne "MISSION_ROOT_ONLY_STAGE_3_8_1"){ Fail "trace tree scope mismatch" }
if($definition.definition.runtime_side_effects -ne $false){ Fail "trace definition must declare no runtime side effects" }
Pass "Canonical observability trace definition is exposed"

Write-Host "`n[8] Final authority / I-O / mutation boundary"
foreach($field in @(
    "observability_trace_telemetry_export_performed",
    "observability_trace_external_network_io_performed",
    "observability_trace_runtime_probe_performed",
    "observability_trace_governance_query_performed",
    "observability_trace_authorization_granted",
    "observability_trace_mission_state_transition_performed",
    "observability_trace_routing_performed",
    "observability_trace_delegation_performed",
    "observability_trace_dispatch_performed",
    "observability_trace_execution_attempt_created",
    "observability_trace_target_action_dispatch_performed",
    "observability_trace_target_actuation"
)){
    if($health.$field -ne $false){ Fail "$field must be false" }
}
Pass "Stage 3.8.1 adds identity/observability semantics only; no operational authority or external I/O"

Write-Host "`n==============================================================================" -ForegroundColor Green
Write-Host "STAGE 3.8.1 ACCEPTANCE: PASS" -ForegroundColor Green
Write-Host "==============================================================================" -ForegroundColor Green
