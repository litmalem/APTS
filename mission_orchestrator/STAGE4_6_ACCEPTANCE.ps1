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
$ExpectedEventControl = "stage4.5-pentest-event-runtime-contract"
$ExpectedControl = "stage4.6-pentest-workflow-orchestrator-skeleton"
$ExpectedSchema = "apts-stage4.6-pentest-workflow-orchestrator-skeleton-v1"
$ExpectedWorkflowSchema = "apts-pentest-workflow-v1"
$ExpectedStartSchema = "apts-pentest-workflow-start-request-v1"
$ExpectedResultSchema = "apts-pentest-workflow-result-v1"
$ExpectedPlaceholderWorker = "PENTEST_PLACEHOLDER_WORKER"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 4
$ExpectedInventory = 1697

Write-Host "=============================================================================="
Write-Host "Stage 4.6 - Pentest Workflow Orchestrator Skeleton"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.6 Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration mismatch" }
if ($health.stage4_6_schema_version -ne $ExpectedSchema) { throw "Stage 4.6 schema mismatch" }
if ($health.stage4_6_workflow_schema_version -ne $ExpectedWorkflowSchema) { throw "Stage 4.6 workflow schema mismatch" }
if ($health.stage4_6_start_request_schema_version -ne $ExpectedStartSchema) { throw "Stage 4.6 start request schema mismatch" }
if ($health.stage4_6_result_schema_version -ne $ExpectedResultSchema) { throw "Stage 4.6 result schema mismatch" }
if ($health.stage4_6_predecessor_control -ne $ExpectedEventControl) { throw "Stage 4.6 predecessor mismatch" }
if ([int]$health.stage4_6_repository_migration_level -ne $ExpectedPentestMigration) { throw "Stage 4.6 migration metadata mismatch" }
if (-not $health.stage4_6_workflow_orchestrator_enabled) { throw "Stage 4.6 workflow orchestrator is not enabled" }
if (-not $health.stage4_6_placeholder_worker_assignment_enabled) { throw "Stage 4.6 placeholder assignment is not enabled" }
if ($health.stage4_6_placeholder_worker_id -ne $ExpectedPlaceholderWorker) { throw "Stage 4.6 placeholder worker mismatch" }
if (-not $health.stage4_6_result_intake_enabled -or -not $health.stage4_6_task_closure_enabled) { throw "Stage 4.6 result/closure semantics not enabled" }
if ($health.stage4_6_full_reasoning_enabled) { throw "Stage 4.6 must not enable full reasoning" }
if ($health.stage4_6_replanning_enabled) { throw "Stage 4.6 must not enable replanning" }
if ($health.stage4_6_capability_registry_enabled) { throw "Stage 4.6 must not enable Stage-4.7 capability registry" }
if ($health.stage4_6_execution_intake_enabled) { throw "Stage 4.6 must not enable execution intake" }
if ($health.stage4_6_tool_invocation_enabled) { throw "Stage 4.6 must not invoke tools" }
if ($health.stage4_6_external_network_io_performed) { throw "Stage 4.6 must not perform external network I/O" }
if ($health.stage4_6_target_actuation) { throw "Stage 4.6 must not actuate targets" }
if ($health.stage4_6_authorization_minting_enabled) { throw "Stage 4.6 must not mint authorization" }
if ($health.stage4_6_next_stage -ne "4.7") { throw "Stage 4.6 next-stage mismatch" }
Write-Host "[PASS] Stage 4.6 runtime active, repository migration 4, non-executing workflow skeleton"

Write-Host "`n[2] Stage 4.1-4.5 predecessor contracts remain available"
$boundaryContract = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
$pipContract = Invoke-RestMethod "$PentestUrl/api/pentest/pip-contract"
$taskContract = Invoke-RestMethod "$PentestUrl/api/pentest/task-contract"
$lifecycleContract = Invoke-RestMethod "$PentestUrl/api/pentest/lifecycle-contract"
$eventContract = Invoke-RestMethod "$PentestUrl/api/pentest/event-contract"
if ($boundaryContract.control_version -ne $ExpectedBoundaryControl -or $boundaryContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.1 projection mismatch" }
if ($pipContract.control_version -ne $ExpectedPipControl -or $pipContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.2 projection mismatch" }
if ($taskContract.control_version -ne $ExpectedTaskControl -or $taskContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.3 projection mismatch" }
if ($lifecycleContract.control_version -ne $ExpectedLifecycleControl -or $lifecycleContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.4 projection mismatch" }
if ($eventContract.control_version -ne $ExpectedEventControl -or $eventContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.5 projection mismatch" }
if (-not $taskContract.workflow_orchestrator_enabled -or -not $lifecycleContract.workflow_orchestrator_enabled -or -not $eventContract.workflow_orchestrator_enabled) { throw "active Stage-4.6 workflow orchestration is not projected through predecessor routes" }
if ($eventContract.stage4_5_definition.workflow_orchestrator_enabled) { throw "Historical Stage 4.5 definition was mutated" }
Write-Host "[PASS] Stage 4.1 + 4.2 + 4.3 + 4.4 + 4.5 predecessors preserved"

Write-Host "`n[3] Canonical Stage 4.6 workflow contract API"
$workflowContract = Invoke-RestMethod "$PentestUrl/api/pentest/workflow-contract"
if ($workflowContract.control_version -ne $ExpectedControl) { throw "workflow contract route control mismatch" }
if ($workflowContract.definition.schema_version -ne $ExpectedSchema) { throw "workflow definition schema mismatch" }
if ($workflowContract.definition.workflow_schema_version -ne $ExpectedWorkflowSchema) { throw "workflow schema mismatch" }
if ($workflowContract.definition.predecessor_control -ne $ExpectedEventControl) { throw "workflow predecessor mismatch" }
if ([int]$workflowContract.definition.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "workflow repository migration mismatch" }
if ($workflowContract.definition.placeholder_worker_id -ne $ExpectedPlaceholderWorker) { throw "workflow placeholder mismatch" }
if (-not $workflowContract.workflow_orchestrator_enabled -or -not $workflowContract.placeholder_worker_assignment_enabled) { throw "workflow skeleton is not enabled" }
if ($workflowContract.full_reasoning_enabled -or $workflowContract.replanning_enabled) { throw "Stage 4.6 crossed reasoning/replanning boundary" }
if ($workflowContract.capability_registry_enabled -or $workflowContract.execution_intake_enabled -or $workflowContract.tool_invocation_enabled -or $workflowContract.target_actuation) { throw "Stage 4.6 crossed Stage 4.7/6 execution boundary" }
Write-Host "[PASS] canonical Stage 4.6 workflow contract"

Write-Host "`n[4] Materialize canonical PIP-bound pentest task"
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
    "objective": {"type":"SECURITY_VALIDATION","description":"Stage 4.6 workflow skeleton acceptance"},
    "constraints": {"max_actions":10,"risk_threshold":"MODERATE","data_handling_policy":{"retain_sensitive_output":False}},
    "roe": {"allowed_action_classes":["TARGET_RECON","VULNERABILITY_VALIDATION"],"prohibited_action_classes":["DESTRUCTIVE_ACTION"],"destructive_actions_allowed":False},
    "authorization_reference": {"policy_decision_id":"decision-stage4-6-acceptance","policy_decision_hash":"d"*64,"policy_version":10,"execution_authorized":True,"pre_dispatch_revalidation_id":"xreval-stage4-6-acceptance"},
}
pip = seal_pip_artifact({
    "schema_version": PIP_SCHEMA_VERSION,
    "pip_id": f"pip-{uuid.uuid4()}",
    "pip_version": "1",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "task_id": boundary["task_id"],
    "source_cti": {"source_type":"CTI","source_system":"VULNDESK_CTI","artifact_id":f"cti-{uuid.uuid4()}","artifact_version":"12","artifact_sha256":"e"*64},
    "issued_at": z(now-timedelta(minutes=5)),
    "expires_at": z(now+timedelta(hours=6)),
    "scope": boundary["scope"],
    "confidence": 0.95,
    "provenance": {"producer":"VULNDESK_CTI","source_refs":["cti-stage4-6-acceptance","cve-CVE-2026-4600"],"collection_method":"CTI_CORRELATION","correlation_id":"corr-stage4-6-acceptance"},
    "intelligence": {"hypotheses":[{"hypothesis_id":"hyp-workflow-acceptance","summary":"workflow skeleton acceptance"}],"observations":[{"kind":"CTI_INDICATOR","value":"service-family-stage46"}]},
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
if ($LASTEXITCODE -ne 0) { throw "failed to construct canonical Stage 4.6 acceptance payload" }
$taskBody = [string]($payloadJson | Select-Object -Last 1)
$create = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body $taskBody
if ($create.status -ne "created") { throw "task materialization did not return created" }
if ($create.lifecycle.state -ne "RECEIVED" -or [int]$create.lifecycle.state_version -ne 1) { throw "initial lifecycle is not RECEIVED/v1" }
if (-not $create.event_emitted -or -not $create.event_persisted) { throw "task materialization root event was not persisted" }
if ($create.workflow_orchestrator_invoked) { throw "task create must not auto-start workflow" }
if ($create.execution_started -or $create.tool_invocation_performed -or $create.target_actuation) { throw "task materialization crossed execution boundary" }
$taskId = $create.record.pentest_task_id
$pentestId = $create.record.pentest_id
Write-Host "[PASS] task materialized in RECEIVED with workflow available but not invoked"

Write-Host "`n[5] Start local workflow skeleton and assign fixed placeholder worker"
$startSuffix = [guid]::NewGuid().ToString("N")
$startBody = @{
    schema_version = $ExpectedStartSchema
    request_id = "pwstart-$startSuffix"
    idempotency_key = "idem-wfstart-$startSuffix"
    actor = "stage4.6-acceptance"
    metadata = @{ acceptance = $true }
} | ConvertTo-Json -Depth 12 -Compress
$started = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/workflow/start" -ContentType "application/json" -Body $startBody
if ($started.status -ne "started" -or -not $started.created) { throw "workflow did not start" }
if ($started.lifecycle.state -ne "RUNNING" -or [int]$started.lifecycle.state_version -ne 5) { throw "workflow did not drive canonical lifecycle to RUNNING/v5" }
if (@($started.lifecycle_transitions).Count -ne 4) { throw "workflow start did not emit four canonical transitions" }
$toStates = @($started.lifecycle_transitions | ForEach-Object { $_.to_state })
if (($toStates -join ",") -ne "VALIDATED,READY,PLANNING,RUNNING") { throw "workflow transition path mismatch: $($toStates -join ',')" }
if ($started.workflow.worker_assignment.worker_id -ne $ExpectedPlaceholderWorker) { throw "placeholder worker mismatch" }
if ($started.workflow.worker_assignment.tool_access -or $started.workflow.worker_assignment.execution_authority) { throw "placeholder worker obtained execution authority" }
if ($started.execution_started -or $started.tool_invocation_performed -or $started.external_network_io_performed -or $started.target_actuation -or $started.authorization_minted) { throw "workflow start crossed execution boundary" }
if ($started.reasoning_performed -or $started.replanning_performed) { throw "workflow start crossed Stage-5 agentic boundary" }
$workflowId = $started.workflow.workflow_id
$eventsAtRun = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/events"
if ([int]$eventsAtRun.count -ne 5) { throw "expected root + four lifecycle events, got $($eventsAtRun.count)" }
Write-Host "[PASS] RECEIVED -> VALIDATED -> READY -> PLANNING -> RUNNING under placeholder workflow"

Write-Host "`n[6] Exact workflow-start replay is idempotent"
$startReplay = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/workflow/start" -ContentType "application/json" -Body $startBody
if ($startReplay.status -ne "replayed" -or $startReplay.created -or -not $startReplay.replayed) { throw "exact workflow-start replay failed" }
if ($startReplay.workflow.workflow_id -ne $workflowId) { throw "workflow-start replay resolved a different workflow" }
if (@($startReplay.lifecycle_transitions).Count -ne 0) { throw "workflow-start replay duplicated lifecycle transitions" }
$eventsAfterReplay = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/events"
if ([int]$eventsAfterReplay.count -ne 5) { throw "workflow-start replay duplicated event ledger" }
Write-Host "[PASS] exact workflow-start replay returned same workflow without duplication"

Write-Host "`n[7] Receive placeholder result and close task through existing lifecycle guards"
$resultSuffix = [guid]::NewGuid().ToString("N")
$resultBody = @{
    schema_version = $ExpectedResultSchema
    result_id = "pwresult-$resultSuffix"
    idempotency_key = "idem-wfresult-$resultSuffix"
    outcome = "SUCCEEDED"
    summary = "Stage 4.6 placeholder result accepted for lifecycle closure; no target action executed."
    evidence_refs = @("evidence-ref:stage4-6-$resultSuffix")
    criteria = @(
        @{ criterion_id = "criterion-evidence-recorded"; status = "SATISFIED" },
        @{ criterion_id = "criterion-scope-preserved"; status = "SATISFIED" }
    )
    metadata = @{ placeholder = $true; acceptance = $true }
} | ConvertTo-Json -Depth 12 -Compress
$closed = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/workflows/$workflowId/result" -ContentType "application/json" -Body $resultBody
if ($closed.status -ne "closed" -or -not $closed.result_created) { throw "workflow result did not close task" }
if ($closed.result.outcome -ne "SUCCEEDED") { throw "workflow result outcome mismatch" }
if ($closed.lifecycle.state -ne "COMPLETED" -or [int]$closed.lifecycle.state_version -ne 6) { throw "workflow result did not close lifecycle at COMPLETED/v6" }
if ($closed.workflow.workflow_status -ne "COMPLETED" -or -not $closed.task_closed) { throw "workflow closure status mismatch" }
if ($closed.execution_started -or $closed.tool_invocation_performed -or $closed.external_network_io_performed -or $closed.target_actuation -or $closed.authorization_minted) { throw "workflow result crossed execution boundary" }
if ($closed.reasoning_performed -or $closed.replanning_performed) { throw "workflow result crossed Stage-5 agentic boundary" }
$eventsAtClose = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/events"
if ([int]$eventsAtClose.count -ne 6) { throw "expected completion event to bring count to 6" }
Write-Host "[PASS] placeholder result -> guarded COMPLETED closure with evidence/criteria binding"

Write-Host "`n[8] Exact result replay is idempotent"
$resultReplay = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/workflows/$workflowId/result" -ContentType "application/json" -Body $resultBody
if ($resultReplay.status -ne "replayed" -or $resultReplay.result_created -or -not $resultReplay.result_replayed) { throw "exact result replay failed" }
$eventsAfterResultReplay = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/events"
if ([int]$eventsAfterResultReplay.count -ne 6) { throw "result replay duplicated completion event" }
Write-Host "[PASS] exact result replay returned same immutable result without duplication"

Write-Host "`n[9] Workflow query + event stream verification"
$workflowQuery = Invoke-RestMethod "$PentestUrl/api/pentest/workflows/$workflowId"
if ($workflowQuery.workflow.workflow_status -ne "COMPLETED") { throw "workflow query status mismatch" }
$taskWorkflowQuery = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/workflow"
if ($taskWorkflowQuery.workflow.workflow_id -ne $workflowId) { throw "task workflow lookup mismatch" }
$resultQuery = Invoke-RestMethod "$PentestUrl/api/pentest/workflows/$workflowId/result"
if ($resultQuery.result.outcome -ne "SUCCEEDED") { throw "workflow result lookup mismatch" }
$verified = Invoke-RestMethod "$PentestUrl/api/pentest/event-streams/$pentestId/verify"
if ($verified.status -ne "VERIFIED") { throw "event stream verification failed" }
if (-not $verified.chain_valid -or -not $verified.source_bindings_valid) { throw "event stream chain/source binding invalid" }
if ([int]$verified.event_count -ne 6) { throw "unexpected verified event count" }
Write-Host "[PASS] workflow/result queries and inherited Stage-4.5 event chain verified"

Write-Host "`n[10] Execution-intake negative boundary"
$dispatchRejected = $false
$errorCode = $null
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        $dispatchRejected = $true
        try {
            $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
            $body = $reader.ReadToEnd() | ConvertFrom-Json
            $errorCode = $body.error_code
        } catch { }
    } else { throw }
}
if (-not $dispatchRejected) { throw "Stage 4.6 execution dispatch was not rejected with HTTP 409" }
if ($errorCode -and $errorCode -ne "STAGE4_6_EXECUTION_INTAKE_NOT_ENABLED") { throw "unexpected dispatch rejection code: $errorCode" }
Write-Host "[PASS] execution dispatch remains disabled and fail-closed"

Write-Host "`n[11] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[12] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[13] Focused Stage 4.6 regression"
python -m pytest -q tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.6 focused regression failed" }

Write-Host "`n[14] Stage 4.1 -> 4.6 regression"
python -m pytest -q `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py `
  tests/test_stage4_5_pentest_event_runtime_contract.py `
  tests/test_stage4_6_pentest_workflow_orchestrator_skeleton.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.1-4.6 regression failed" }

Write-Host "`n[15] Critical Stage 3 + Stage 4 predecessor regression"
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
if ($LASTEXITCODE -ne 0) { throw "Stage 4.6 critical predecessor regression failed" }

Write-Host "`n[16] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.6 Pentest Workflow Orchestrator Skeleton"
Write-Host "control_version  : $ExpectedControl"
Write-Host "mission migration: $ExpectedMissionMigration"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.5 Pentest Event Runtime & Contract"
Write-Host "workflow         : receive -> track -> placeholder -> state -> result -> close"
Write-Host "semantics        : no full reasoning/replanning; no capability/tool execution; no target actuation"
Write-Host "next             : Stage 4.7 - Capability Registry & Tool Contract"
Write-Host "=============================================================================="
