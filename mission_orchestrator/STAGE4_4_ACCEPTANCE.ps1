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
$ExpectedControl = "stage4.4-pentest-lifecycle-state"
$ExpectedSchema = "apts-stage4.4-pentest-lifecycle-state-v1"
$ExpectedStateSchema = "apts-pentest-lifecycle-state-v1"
$ExpectedTransitionSchema = "apts-pentest-lifecycle-transition-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 2
$ExpectedInventory = 1646

Write-Host "=============================================================================="
Write-Host "Stage 4.4 - Pentest Lifecycle & State"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.4 Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration mismatch" }
if ($health.stage4_4_schema_version -ne $ExpectedSchema) { throw "Stage 4.4 schema mismatch" }
if ($health.stage4_4_state_schema_version -ne $ExpectedStateSchema) { throw "Stage 4.4 state schema mismatch" }
if ($health.stage4_4_transition_schema_version -ne $ExpectedTransitionSchema) { throw "Stage 4.4 transition schema mismatch" }
if ($health.stage4_4_predecessor_control -ne $ExpectedTaskControl) { throw "Stage 4.4 predecessor mismatch" }
if (-not $health.stage4_4_lifecycle_runtime_enabled) { throw "Stage 4.4 lifecycle runtime is not enabled" }
if (-not $health.stage4_4_state_machine_enabled) { throw "Stage 4.4 state machine is not enabled" }
if ($health.stage4_4_event_runtime_enabled) { throw "Stage 4.4 must not enable Stage-4.5 event runtime" }
if ($health.stage4_4_workflow_orchestrator_enabled) { throw "Stage 4.4 must not enable Stage-4.6 workflow orchestrator" }
if ($health.stage4_4_execution_intake_enabled) { throw "Stage 4.4 must not enable execution intake" }
if ($health.stage4_4_tool_invocation_enabled) { throw "Stage 4.4 must not invoke tools" }
if ($health.stage4_4_target_actuation) { throw "Stage 4.4 must not actuate targets" }
if ($health.stage4_4_next_stage -ne "4.5") { throw "Stage 4.4 next-stage mismatch" }
if (@($health.stage4_4_states).Count -ne 9) { throw "Stage 4.4 state count mismatch" }
if (@($health.stage4_4_guard_ids).Count -ne 11) { throw "Stage 4.4 guard count mismatch" }
Write-Host "[PASS] Stage 4.4 runtime active, repository migration 2, state-only"

Write-Host "`n[2] Stage 4.1/4.2/4.3 predecessor contracts remain available"
$boundary = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
$pipContract = Invoke-RestMethod "$PentestUrl/api/pentest/pip-contract"
$taskContract = Invoke-RestMethod "$PentestUrl/api/pentest/task-contract"
if ($boundary.control_version -ne $ExpectedBoundaryControl -or $boundary.active_control_version -ne $ExpectedControl) { throw "Stage 4.1 projection mismatch" }
if ($pipContract.control_version -ne $ExpectedPipControl -or $pipContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.2 projection mismatch" }
if ($taskContract.control_version -ne $ExpectedTaskControl -or $taskContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.3 projection mismatch" }
if (-not $taskContract.lifecycle_runtime_enabled) { throw "Stage 4.3 projection did not expose active Stage-4.4 lifecycle" }
if ($taskContract.execution_intake_enabled) { throw "Stage 4.3 projection incorrectly enables execution" }
Write-Host "[PASS] Stage 4.1 + 4.2 + 4.3 predecessors preserved"

Write-Host "`n[3] Canonical Stage 4.4 lifecycle contract API"
$lifecycleContract = Invoke-RestMethod "$PentestUrl/api/pentest/lifecycle-contract"
if ($lifecycleContract.control_version -ne $ExpectedControl) { throw "lifecycle contract route control mismatch" }
if ($lifecycleContract.definition.schema_version -ne $ExpectedSchema) { throw "lifecycle definition schema mismatch" }
if ($lifecycleContract.definition.state_schema_version -ne $ExpectedStateSchema) { throw "state schema mismatch" }
if ($lifecycleContract.definition.transition_schema_version -ne $ExpectedTransitionSchema) { throw "transition schema mismatch" }
if ($lifecycleContract.definition.predecessor_control -ne $ExpectedTaskControl) { throw "lifecycle predecessor mismatch" }
if ([int]$lifecycleContract.definition.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "lifecycle repository migration mismatch" }
if (@($lifecycleContract.definition.states).Count -ne 9) { throw "lifecycle state count mismatch" }
if (@($lifecycleContract.definition.guard_ids).Count -ne 11) { throw "lifecycle guard count mismatch" }
if (-not $lifecycleContract.state_machine_enabled) { throw "state machine not enabled" }
if ($lifecycleContract.event_runtime_enabled) { throw "event runtime enabled too early" }
if ($lifecycleContract.workflow_orchestrator_enabled) { throw "workflow orchestrator enabled too early" }
if ($lifecycleContract.execution_intake_enabled) { throw "execution intake enabled too early" }
Write-Host "[PASS] canonical Stage 4.4 lifecycle contract"

Write-Host "`n[4] Materialize canonical PIP-bound task and initialize RECEIVED lifecycle"
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
    "objective": {"type":"SECURITY_VALIDATION","description":"Stage 4.4 lifecycle acceptance"},
    "constraints": {"max_actions":10,"risk_threshold":"MODERATE","data_handling_policy":{"retain_sensitive_output":False}},
    "roe": {"allowed_action_classes":["TARGET_RECON","VULNERABILITY_VALIDATION"],"prohibited_action_classes":["DESTRUCTIVE_ACTION"],"destructive_actions_allowed":False},
    "authorization_reference": {"policy_decision_id":"decision-stage4-4-acceptance","policy_decision_hash":"d"*64,"policy_version":10,"execution_authorized":True,"pre_dispatch_revalidation_id":"xreval-stage4-4-acceptance"},
}
pip = seal_pip_artifact({
    "schema_version": PIP_SCHEMA_VERSION,
    "pip_id": f"pip-{uuid.uuid4()}",
    "pip_version": "1",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "task_id": boundary["task_id"],
    "source_cti": {"source_type":"CTI","source_system":"VULNDESK_CTI","artifact_id":f"cti-{uuid.uuid4()}","artifact_version":"10","artifact_sha256":"e"*64},
    "issued_at": z(now-timedelta(minutes=5)),
    "expires_at": z(now+timedelta(hours=6)),
    "scope": boundary["scope"],
    "confidence": 0.94,
    "provenance": {"producer":"VULNDESK_CTI","source_refs":["cti-stage4-4-acceptance","cve-CVE-2026-4444"],"collection_method":"CTI_CORRELATION","correlation_id":"corr-stage4-4-acceptance"},
    "intelligence": {"hypotheses":[{"hypothesis_id":"hyp-acceptance","summary":"lifecycle acceptance"}],"observations":[{"kind":"CTI_INDICATOR","value":"service-family-stage44"}]},
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
if ($LASTEXITCODE -ne 0) { throw "failed to construct canonical Stage 4.4 acceptance payload" }
$taskBody = [string]($payloadJson | Select-Object -Last 1)
$create = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body $taskBody
if ($create.status -ne "created") { throw "task materialization did not return created" }
if (-not $create.lifecycle_initialized) { throw "Stage 4.4 lifecycle was not initialized" }
if ($create.lifecycle.state -ne "RECEIVED" -or [int]$create.lifecycle.state_version -ne 1) { throw "initial lifecycle is not RECEIVED/v1" }
if ($create.accepted_for_execution -or $create.tool_invocation_performed -or $create.target_actuation) { throw "task materialization crossed execution boundary" }
$taskId = $create.record.pentest_task_id
Write-Host "[PASS] task materialized and initialized to RECEIVED without execution"

function Invoke-LifecycleTransition {
    param(
        [int]$ExpectedVersion,
        [string]$ToState,
        [hashtable]$Metadata = @{},
        [string[]]$EvidenceRefs = @()
    )
    $suffix = [guid]::NewGuid().ToString("N")
    $body = @{
        transition_id = "ptrans-$suffix"
        idempotency_key = "idem-$suffix"
        expected_state_version = $ExpectedVersion
        to_state = $ToState
        actor = "stage4.4-acceptance"
        reason_code = "TO_$ToState"
        reason = "Stage 4.4 acceptance transition to $ToState"
        evidence_refs = $EvidenceRefs
        metadata = $Metadata
    } | ConvertTo-Json -Depth 12 -Compress
    return Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions" -ContentType "application/json" -Body $body
}

Write-Host "`n[5] Guarded canonical lifecycle progression"
$v = Invoke-LifecycleTransition -ExpectedVersion 1 -ToState "VALIDATED"
if ($v.state.state -ne "VALIDATED" -or [int]$v.state.state_version -ne 2) { throw "VALIDATED transition failed" }
$r = Invoke-LifecycleTransition -ExpectedVersion 2 -ToState "READY"
if ($r.state.state -ne "READY" -or [int]$r.state.state_version -ne 3) { throw "READY transition failed" }
$p = Invoke-LifecycleTransition -ExpectedVersion 3 -ToState "PLANNING"
if ($p.state.state -ne "PLANNING" -or [int]$p.state.state_version -ne 4) { throw "PLANNING transition failed" }
$run = Invoke-LifecycleTransition -ExpectedVersion 4 -ToState "RUNNING"
if ($run.state.state -ne "RUNNING" -or [int]$run.state.state_version -ne 5) { throw "RUNNING transition failed" }
if ($run.execution_started -or $run.tool_invocation_performed -or $run.target_actuation) { throw "RUNNING state incorrectly triggered execution" }
Write-Host "[PASS] RECEIVED -> VALIDATED -> READY -> PLANNING -> RUNNING"

Write-Host "`n[6] WAITING guard and explicit resolution"
$waitRejected = $false
try {
    $null = Invoke-LifecycleTransition -ExpectedVersion 5 -ToState "WAITING"
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $waitRejected = $true } else { throw }
}
if (-not $waitRejected) { throw "WAITING without wait context was not rejected" }
$wait = Invoke-LifecycleTransition -ExpectedVersion 5 -ToState "WAITING" -Metadata @{ wait = @{ reason = "approval dependency"; resume_target = "RUNNING" } }
if ($wait.state.state -ne "WAITING" -or [int]$wait.state.state_version -ne 6) { throw "WAITING transition failed" }
$resume = Invoke-LifecycleTransition -ExpectedVersion 6 -ToState "RUNNING" -Metadata @{ wait_resolution = @{ status = "RESOLVED"; resolution_ref = "approval:stage44:acceptance"; resume_target = "RUNNING" } }
if ($resume.state.state -ne "RUNNING" -or [int]$resume.state.state_version -ne 7) { throw "WAITING resolution transition failed" }
Write-Host "[PASS] WAITING requires explicit context and resolution"

Write-Host "`n[7] Completion guard and terminal immutability"
$completionRejected = $false
try {
    $null = Invoke-LifecycleTransition -ExpectedVersion 7 -ToState "COMPLETED" -Metadata @{ completion = @{ status = "SATISFIED"; criteria = @() } }
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $completionRejected = $true } else { throw }
}
if (-not $completionRejected) { throw "incomplete completion declaration was not rejected" }
$completed = Invoke-LifecycleTransition -ExpectedVersion 7 -ToState "COMPLETED" -EvidenceRefs @("evidence-ref:stage44:acceptance") -Metadata @{ completion = @{ status = "SATISFIED"; criteria = @(
    @{ criterion_id = "criterion-evidence-recorded"; status = "SATISFIED" },
    @{ criterion_id = "criterion-scope-preserved"; status = "SATISFIED" }
) } }
if ($completed.state.state -ne "COMPLETED" -or [int]$completed.state.state_version -ne 8) { throw "COMPLETED transition failed" }
if (-not $completed.state.terminal) { throw "COMPLETED not marked terminal" }
if (@($completed.state.allowed_targets).Count -ne 0) { throw "terminal state exposes allowed targets" }
$terminalRejected = $false
try {
    $null = Invoke-LifecycleTransition -ExpectedVersion 8 -ToState "FAILED"
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $terminalRejected = $true } else { throw }
}
if (-not $terminalRejected) { throw "terminal lifecycle was mutable" }
$history = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId/lifecycle/transitions"
if ([int]$history.count -ne 7) { throw "unexpected successful transition journal count: $($history.count)" }
Write-Host "[PASS] completion guard, terminal immutability, transition journal"

Write-Host "`n[8] Execution-intake negative boundary"
$dispatchRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $dispatchRejected = $true } else { throw }
}
if (-not $dispatchRejected) { throw "Stage 4.4 execution dispatch was not rejected with HTTP 409" }
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

Write-Host "`n[11] Focused Stage 4.4 regression"
python -m pytest -q tests/test_stage4_4_pentest_lifecycle_state.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.4 focused regression failed" }

Write-Host "`n[12] Critical Stage 3 + Stage 4 predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py `
  tests/test_stage4_4_pentest_lifecycle_state.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.4 critical predecessor regression failed" }

Write-Host "`n[13] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.4 Pentest Lifecycle & State"
Write-Host "control_version  : $ExpectedControl"
Write-Host "mission migration: $ExpectedMissionMigration"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.3 Pentest Mission & Task Contract"
Write-Host "lifecycle        : guarded durable state machine; optimistic state versioning"
Write-Host "semantics        : state only; no event runtime; no workflow execution; no actuation"
Write-Host "next             : Stage 4.5 - Pentest Event Runtime & Contract"
Write-Host "=============================================================================="
