param([string]$MissionBaseUrl = 'http://127.0.0.1:8780')
$ErrorActionPreference = 'Stop'
function Fail([string]$Reason) { Write-Host "STAGE 3.8.4 ACCEPTANCE: FAIL - $Reason" -ForegroundColor Red; exit 1 }
function Pass([string]$Reason) { Write-Host "[PASS] $Reason" -ForegroundColor Green }
Set-Location $PSScriptRoot
try { $health = Invoke-RestMethod "$MissionBaseUrl/health" } catch { Fail "runtime unavailable: $($_.Exception.Message)" }
if ($health.control_version -ne 'stage3.8.4-live-mission-state-execution-projection') { Fail 'runtime control not active; install package and restart service' }
if ($health.mission_repository_migration_level -ne 53) { Fail 'migration level mismatch' }
if ($health.live_mission_state_execution_projection_schema_version -ne 'apts-live-mission-state-execution-projection-v1') { Fail 'projection schema mismatch' }
if ($health.live_mission_state_execution_projection_read_only -ne $true -or $health.live_mission_state_execution_projection_deterministic -ne $true -or $health.live_mission_state_execution_projection_restart_stable -ne $true) { Fail 'projection invariants inactive' }
if ($health.live_mission_state_execution_projection_new_durable_store_added -ne $false) { Fail 'unexpected durable store' }
Pass 'runtime contract active'
& python -m compileall -q mission_orchestrator run tests
if ($LASTEXITCODE -ne 0) { Fail 'Python compilation failed' }
Pass 'Python compilation'
$collect = (& python -m pytest --collect-only -q 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $collect -notmatch '(?m)^1389 tests collected') { Fail 'canonical inventory must contain 1389 tests' }
Pass '1389 tests collected'
$full = (& python -m pytest -q 2>&1 | Out-String)
Write-Host $full.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $full -notmatch '(?m)^1389 passed') { Fail 'full regression failed' }
Pass 'full regression'
$focused = (& python -m pytest -q tests/test_stage3_8_4_live_mission_state_execution_projection.py tests/test_stage3_8_3_global_causal_lineage_graph.py tests/test_stage3_8_2_event_normalization_ingestion.py tests/test_stage3_8_1_canonical_observability_trace_identity_contract.py 2>&1 | Out-String)
Write-Host $focused.TrimEnd()
if ($LASTEXITCODE -ne 0 -or $focused -notmatch '(?m)^33 passed') { Fail 'focused regression failed' }
Pass '33 focused tests'
Write-Host 'STAGE 3.8.4 ACCEPTANCE: PASS' -ForegroundColor Green
