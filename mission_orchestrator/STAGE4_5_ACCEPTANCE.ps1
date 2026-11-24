param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedBoundaryControl = "stage4.1-pentest-boundary-canonical-contract"
$ExpectedPipControl = "stage4.2-pip-ingestion-validation-binding"
$ExpectedTaskControl = "stage4.3-pentest-mission-task-contract"
$ExpectedLifecycleControl = "stage4.4-pentest-lifecycle-state"
$ExpectedControl = "stage4.5-pentest-event-runtime-contract"
$ExpectedSchema = "apts-stage4.5-pentest-event-runtime-contract-v1"
$ExpectedEventSchema = "apts-pentest-event-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 3
$ExpectedInventory = 1671

Write-Host "=============================================================================="
Write-Host "Stage 4.5 - Pentest Event Runtime & Contract"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.5 Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration mismatch" }
if ($health.stage4_5_schema_version -ne $ExpectedSchema) { throw "Stage 4.5 schema mismatch" }
if ($health.stage4_5_event_schema_version -ne $ExpectedEventSchema) { throw "Stage 4.5 event schema mismatch" }
if ($health.stage4_5_predecessor_control -ne $ExpectedLifecycleControl) { throw "Stage 4.5 predecessor mismatch" }
if (-not $health.stage4_5_event_runtime_enabled) { throw "Stage 4.5 event runtime is not enabled" }
if (-not $health.stage4_5_event_persistence_enabled) { throw "Stage 4.5 event persistence is not enabled" }
if (-not $health.stage4_5_event_hash_chain_enabled) { throw "Stage 4.5 event hash chain is not enabled" }
if (-not $health.stage4_5_event_startup_reconciliation_enabled) { throw "Stage 4.5 event reconciliation is not enabled" }
if ($health.stage4_5_workflow_orchestrator_enabled) { throw "Stage 4.5 must not enable Stage-4.6 workflow orchestrator" }
if ($health.stage4_5_capability_registry_enabled) { throw "Stage 4.5 must not enable Stage-4.7 capability registry" }
if ($health.stage4_5_execution_intake_enabled) { throw "Stage 4.5 must not enable execution intake" }
if ($health.stage4_5_tool_invocation_enabled) { throw "Stage 4.5 must not invoke tools" }
if ($health.stage4_5_target_actuation) { throw "Stage 4.5 must not actuate targets" }
if ($health.stage4_5_next_stage -ne "4.6") { throw "Stage 4.5 next-stage mismatch" }
if (@($health.stage4_5_required_fields).Count -ne 10) { throw "Stage 4.5 canonical field count mismatch" }
if (@($health.stage4_5_event_types).Count -ne 2) { throw "Stage 4.5 event type count mismatch" }
Write-Host "[PASS] Stage 4.5 runtime active, repository migration 3, event-only extension"

Write-Host "`n[2] Stage 4.1/4.2/4.3/4.4 predecessor contracts remain available"
$boundaryContract = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
$pipContract = Invoke-RestMethod "$PentestUrl/api/pentest/pip-contract"
$taskContract = Invoke-RestMethod "$PentestUrl/api/pentest/task-contract"
$lifecycleContract = Invoke-RestMethod "$PentestUrl/api/pentest/lifecycle-contract"
if ($boundaryContract.control_version -ne $ExpectedBoundaryControl -or $boundaryContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.1 projection mismatch" }
if ($pipContract.control_version -ne $ExpectedPipControl -or $pipContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.2 projection mismatch" }
if ($taskContract.control_version -ne $ExpectedTaskControl -or $taskContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.3 projection mismatch" }
if ($lifecycleContract.control_version -ne $ExpectedLifecycleControl -or $lifecycleContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.4 projection mismatch" }
if (-not $taskContract.event_runtime_enabled -or -not $lifecycleContract.event_runtime_enabled) { throw "active Stage-4.5 event runtime not projected through predecessors" }
if ($lifecycleContract.workflow_orchestrator_enabled) { throw "Stage 4.4 projection incorrectly enables workflow orchestration" }
Write-Host "[PASS] Stage 4.1 + 4.2 + 4.3 + 4.4 predecessors preserved"

Write-Host "`n[3] Canonical Stage 4.5 event contract API"
$eventContract = Invoke-RestMethod "$PentestUrl/api/pentest/event-contract"
if ($eventContract.control_version -ne $ExpectedControl) { throw "event contract route control mismatch" }
if ($eventContract.definition.schema_version -ne $ExpectedSchema) { throw "event definition schema mismatch" }
if ($eventContract.definition.event_schema_version -ne $ExpectedEventSchema) { throw "event schema mismatch" }
if ($eventContract.definition.predecessor_control -ne $ExpectedLifecycleControl) { throw "event predecessor mismatch" }
if ([int]$eventContract.definition.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "event repository migration mismatch" }
if (@($eventContract.definition.required_fields).Count -ne 10) { throw "canonical event field count mismatch" }
if (@($eventContract.definition.event_types).Count -ne 2) { throw "canonical event type count mismatch" }
if (-not $eventContract.event_runtime_enabled -or -not $eventContract.event_persistence_enabled -or -not $eventContract.event_hash_chain_enabled) { throw "event runtime contract is not fully enabled" }
if ($eventContract.workflow_orchestrator_enabled -or $eventContract.execution_intake_enabled -or $eventContract.target_actuation) { throw "Stage 4.5 contract crossed execution boundary" }
Write-Host "[PASS] canonical Stage 4.5 event contract"

Write-Host "`n[4] Materialize canonical PIP-bound task and require PENTEST_TASK_RECEIVED event"
$payloadJson = @'
import json, uuid
from datetime import datetime, timedelta, timezone
from pentest_subsystem.pip_contract import PIP_SCHEMA_VERSION, build_pip_ingestion_binding, seal_pip_artifact
from pentest_subsystem.task_contract import PENTEST_TASK_ARTIFACT_SCHEMA_VERSION, seal_pentest_task_artifact

def z(v):
    return v.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

now = datetime.now(timezone.utc)
boundary = {
    "pentest_id": f"pentest-{uuid.uuid4()}",
    "mission_id": f"mission-gmo-{uuid.uuid4()}",
    "task_id": f"ptask-{uuid.uuid4()}",
    "scope": {
        "targets": [
            {"target_type":"HOST","target_value":"lab-a.internal"},
            {"target_type":"HOST","target_value":"lab-b.internal"},
        ],
        "excluded_targets": [{"target_type":"HOST","target_value":"lab-admin.internal"}],
        "network_zone":"AUTHORIZED_LAB",
    },
    "objective": {"type":"SECURITY_VALIDATION","description":"Stage 4.5 event acceptance"},
    "constraints": {"max_actions":10,"risk_threshold":"MODERATE","data_handling_policy":{"retain_sensitive_output":False}},
    "roe": {"allowed_action_classes":["TARGET_RECON","VULNERABILITY_VALIDATION"],"prohibited_action_classes":["DESTRUCTIVE_ACTION"],"destructive_actions_allowed":False},
    "authorization_reference": {"policy_decision_id":"decision-stage4-5-acceptance","policy_decision_hash":"d"*64,"policy_version":10,"execution_authorized":True,"pre_dispatch_revalidation_id":"xreval-stage4-5-acceptance"},
}
pip = seal_pip_artifact({
    "schema_version": PIP_SCHEMA_VERSION,
    "pip_id": f"pip-{uuid.uuid4()}",
    "pip_version": "1",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "task_id": boundary["task_id"],
    "source_cti": {"source_type":"CTI","source_system":"VULNDESK_CTI","artifact_id":f"cti-{uuid.uuid4()}","artifact_version":"11","artifact_sha256":"e"*64},
    "issued_at": z(now-timedelta(minutes=5)),
    "expires_at": z(now+timedelta(hours=6)),
    "scope": boundary["scope"],
    "confidence": 0.95,
    "provenance": {"producer":"VULNDESK_CTI","source_refs":["cti-stage4-5-acceptance","cve-CVE-2026-4500"],"collection_method":"CTI_CORRELATION","correlation_id":"corr-stage4-5-acceptance"},
    "intelligence": {"hypotheses":[{"hypothesis_id":"hyp-event-acceptance","summary":"event runtime acceptance"}],"observations":[{"kind":"CTI_INDICATOR","value":"service-family-stage45"}]},
})
pip_binding = build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=pip, now=now)
target = boundary["scope"]["targets"][0]
task = seal_pentest_task_artifact({
    "schema_version": PENTEST_TASK_ARTIFACT_SCHEMA_VERSION,
    "pentest_task_id": f"pentest-task-{uuid.uuid4()}",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "upstream_task_id": boundary["task_id"],
    "pip_reference": {"pip_id":pip["pip_id"],"pip_version":pip["pip_version"],"pip_artifact_sha256":pip["integrity"]["canonical_sha256"],"pip_binding_sha256":pip_binding["integrity"]["canonical_sha256"]},
    "target": target,
    "scope": {"targets":[target],"excluded_targets":boundary["scope"]["excluded_targets"],"network_zone":boundary["scope"]["network_zone"]},
    "objective": boundary["objective"],
    "constraints": boundary["constraints"],
    "evidence_requirement": {"minimum_evidence_items":1,"required_artifact_types":["OBSERVATION","TRACE"],"integrity_required":True,"provenance_required":True},
    "authorization_reference": boundary["authorization_reference"],
    "completion_criteria": {"all_required":True,"criteria":[
        {"criterion_id":"criterion-evidence-recorded","type":"EVIDENCE_PRESENT","description":"Required evidence references are declared.","required":True},
        {"criterion_id":"criterion-scope-preserved","type":"SCOPE_PRESERVED","description":"Declared task scope remains preserved.","required":True},
    ]},
    "created_at": z(now),
})
print(json.dumps({"boundary":boundary,"pip":pip,"task":task}, separators=(",",":")))
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "failed to construct canonical Stage 4.5 acceptance payload" }
$taskBody = [string]($payloadJson | Select-Object -Last 1)
$create = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body $taskBody
if ($create.status -ne "created") { throw "task materialization did not return created" }
if ($create.lifecycle.state -ne "RECEIVED" -or [int]$create.lifecycle.state_version -ne 1) { throw "initial lifecycle is not RECEIVED/v1" }
if (-not $create.event_emitted -or -not $create.event_persisted) { throw "task materialization event was not persisted" }
if ($create.event.event_type -ne "PENTEST_TASK_RECEIVED") { throw "unexpected task event type" }
if ([int]$create.event.event_sequence -ne 1) { throw "task event is not stream root" }
if ($create.event.state_before -ne $null -or $create.event.state_after -ne "RECEIVED") { throw "task event state projection mismatch" }
if ($create.execution_started -or $create.tool_invocation_performed -or $create.target_actuation) { throw "task materialization crossed execution boundary" }
$taskId = $create.record.pentest_task_id
$pentestId = $create.record.pentest_id
Write-Host "[PASS] task materialized with canonical durable root event"

function New-LifecycleTransitionBody {
    param(
        [int]$ExpectedVersion,
        [string]$ToState,
        [string]$Suffix
    )
    return @{
        transition_id = "ptrans-$Suffix"
        idempotency_key = "idem-$Suffix"
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage4.5-acceptance"
        reason_code = "TO_$ToState"
        reason = "Stage 4.5 acceptance transition to $ToState"
        evidence_refs = @()
        metadata = @{}
    } | ConvertTo-Json -Depth 12 -Compress
}

Write-Host "`n[5] Guarded lifecycle progression emits canonical transition events"
$bodyValidated = New-LifecycleTransitionBody -ExpectedVersion 1 -ToState "VALIDATED" -Suffix ([guid]::NewGuid().ToString("N"))
$v = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $bodyValidated
$bodyReady = New-LifecycleTransitionBody -ExpectedVersion 2 -ToState "READY" -Suffix ([guid]::NewGuid().ToString("N"))
$r = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $bodyReady
$bodyPlanning = New-LifecycleTransitionBody -ExpectedVersion 3 -ToState "PLANNING" -Suffix ([guid]::NewGuid().ToString("N"))
$p = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $bodyPlanning
$bodyRunning = New-LifecycleTransitionBody -ExpectedVersion 4 -ToState "RUNNING" -Suffix ([guid]::NewGuid().ToString("N"))
$run = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $bodyRunning
foreach ($item in @($v,$r,$p,$run)) {
    if (-not $item.event_emitted -or -not $item.event_persisted) { throw "lifecycle transition did not persist canonical event" }
    if ($item.event.event_type -ne "PENTEST_LIFECYCLE_STATE_TRANSITIONED") { throw "unexpected lifecycle event type" }
    if ($item.execution_started -or $item.tool_invocation_performed -or $item.target_actuation) { throw "lifecycle event crossed execution boundary" }
}
if ($run.state.state -ne "RUNNING" -or [int]$run.state.state_version -ne 5) { throw "RUNNING transition failed" }
if ([int]$run.event.event_sequence -ne 5) { throw "unexpected event sequence at RUNNING" }
Write-Host "[PASS] RECEIVED -> VALIDATED -> READY -> PLANNING -> RUNNING emitted ordered events"

Write-Host "`n[6] Exact transition replay is event-idempotent"
$replay = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $bodyRunning
if (-not $replay.replayed -or $replay.applied) { throw "exact lifecycle replay did not return replayed" }
if (-not $replay.event_replayed -or $replay.event.event_id -ne $run.event.event_id) { throw "event replay did not resolve the same canonical event" }
$events = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/events"
if ([int]$events.count -ne 5) { throw "event replay duplicated the event ledger: $($events.count)" }
Write-Host "[PASS] exact lifecycle replay returned same event without duplication"

Write-Host "`n[7] Event stream integrity/source verification"
$verified = Invoke-RestMethod "$PentestUrl/api/pentest/event-streams/$pentestId/verify"
if ($verified.status -ne "VERIFIED") { throw "event stream verification failed" }
if (-not $verified.chain_valid -or -not $verified.source_bindings_valid) { throw "event stream chain/source binding invalid" }
if ([int]$verified.event_count -ne 5) { throw "unexpected verified event count" }
$eventById = Invoke-RestMethod "$PentestUrl/api/pentest/events/$($run.event.event_id)"
if ($eventById.event.canonical_sha256 -ne $run.event.canonical_sha256) { throw "event lookup changed canonical hash" }
Write-Host "[PASS] append-only per-Pentest hash chain and source binding verified"

Write-Host "`n[8] Execution-intake negative boundary"
$dispatchRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $dispatchRejected = $true } else { throw }
}
if (-not $dispatchRejected) { throw "Stage 4.5 execution dispatch was not rejected with HTTP 409" }
Write-Host "[PASS] execution dispatch remains disabled"

Write-Host "`n[9] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[10] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[11] Focused Stage 4.5 regression"
python -m pytest -q tests/test_stage4_5_pentest_event_runtime_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.5 focused regression failed" }

Write-Host "`n[12] Stage 4.1 -> 4.5 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.5 regression failed" }

Write-Host "`n[13] Critical Stage 3 + Stage 4 predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.5 critical predecessor regression failed" }

Write-Host "`n[14] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.5 Pentest Event Runtime & Contract"
Write-Host "control_version  : $ExpectedControl"
Write-Host "mission migration: $ExpectedMissionMigration"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.4 Pentest Lifecycle & State"
Write-Host "event runtime    : durable append-only per-Pentest hash chain"
Write-Host "semantics        : events only; no workflow orchestrator; no tool execution; no actuation"
Write-Host "next             : Stage 4.6 - Pentest Workflow Orchestrator Skeleton"
Write-Host "=============================================================================="
