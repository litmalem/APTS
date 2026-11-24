param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedBoundaryControl = "stage4.1-pentest-boundary-canonical-contract"
$ExpectedPipControl = "stage4.2-pip-ingestion-validation-binding"
$ExpectedControl = "stage4.3-pentest-mission-task-contract"
$ExpectedSchema = "apts-stage4.3-pentest-mission-task-contract-v1"
$ExpectedTaskSchema = "apts-pentest-task-contract-v1"
$ExpectedBindingSchema = "apts-stage4.3-pentest-task-binding-envelope-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 1
$ExpectedInventory = 1623

Write-Host "=============================================================================="
Write-Host "Stage 4.3 - Pentest Mission & Task Contract"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.3 Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration mismatch" }
if ($health.stage4_3_schema_version -ne $ExpectedSchema) { throw "Stage 4.3 schema mismatch" }
if ($health.stage4_3_task_schema_version -ne $ExpectedTaskSchema) { throw "Pentest task schema mismatch" }
if ($health.stage4_3_binding_envelope_schema_version -ne $ExpectedBindingSchema) { throw "Pentest task binding schema mismatch" }
if ($health.stage4_3_predecessor_control -ne $ExpectedPipControl) { throw "Stage 4.3 predecessor mismatch" }
if (-not $health.stage4_3_local_task_repository_enabled) { throw "Stage 4.3 local task repository is not enabled" }
if (-not $health.stage4_3_durable_persistence_enabled) { throw "Stage 4.3 durable persistence is not enabled" }
if (-not $health.stage4_3_pip_binding_required) { throw "Stage 4.3 PIP binding must be required" }
if ($health.stage4_3_lifecycle_runtime_enabled) { throw "Stage 4.3 must not enable Stage-4.4 lifecycle runtime" }
if ($health.stage4_3_execution_intake_enabled) { throw "Stage 4.3 must not enable execution intake" }
if ($health.stage4_3_tool_invocation_enabled) { throw "Stage 4.3 must not invoke Pentest tools" }
if ($health.stage4_3_target_actuation) { throw "Stage 4.3 must not actuate targets" }
if ($health.stage4_3_next_stage -ne "4.4") { throw "Stage 4.3 next-stage mismatch" }
if (@($health.stage4_3_roadmap_fields).Count -ne 8) { throw "Stage 4.3 roadmap-field count mismatch" }
if (@($health.stage4_3_binding_dimensions).Count -ne 9) { throw "Stage 4.3 binding-dimension count mismatch" }
Write-Host "[PASS] Stage 4.3 runtime active, repository migration 1, non-executing"

Write-Host "`n[2] Stage 4.1 and Stage 4.2 canonical predecessors remain available"
$boundaryContract = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
if ($boundaryContract.control_version -ne $ExpectedBoundaryControl) { throw "Stage 4.1 boundary control mismatch" }
if ($boundaryContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.1 active-control projection mismatch" }
$pipContract = Invoke-RestMethod "$PentestUrl/api/pentest/pip-contract"
if ($pipContract.control_version -ne $ExpectedPipControl) { throw "Stage 4.2 PIP control mismatch" }
if ($pipContract.active_control_version -ne $ExpectedControl) { throw "Stage 4.2 active-control projection mismatch" }
if (-not $pipContract.pip_is_intelligence_input) { throw "PIP predecessor semantics changed" }
if ($pipContract.execution_intake_enabled) { throw "PIP predecessor incorrectly enables execution" }
Write-Host "[PASS] Stage 4.1 boundary + Stage 4.2 PIP predecessor preserved"

Write-Host "`n[3] Canonical Stage 4.3 task contract API"
$taskContract = Invoke-RestMethod "$PentestUrl/api/pentest/task-contract"
if ($taskContract.control_version -ne $ExpectedControl) { throw "task contract route control mismatch" }
if ($taskContract.definition.schema_version -ne $ExpectedSchema) { throw "task contract definition schema mismatch" }
if ($taskContract.definition.task_schema_version -ne $ExpectedTaskSchema) { throw "task artifact schema mismatch" }
if ($taskContract.definition.binding_envelope_schema_version -ne $ExpectedBindingSchema) { throw "task binding envelope schema mismatch" }
if ($taskContract.definition.predecessor_control -ne $ExpectedPipControl) { throw "task predecessor mismatch" }
if ([int]$taskContract.definition.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "task contract migration mismatch" }
if (-not $taskContract.local_task_repository_enabled) { throw "task contract repository not enabled" }
if (-not $taskContract.durable_persistence_enabled) { throw "task contract persistence not enabled" }
if ($taskContract.lifecycle_runtime_enabled) { throw "task contract incorrectly enables lifecycle runtime" }
if ($taskContract.execution_intake_enabled) { throw "task contract incorrectly enables execution" }
if ($taskContract.target_actuation) { throw "task contract incorrectly enables target actuation" }
Write-Host "[PASS] canonical Stage 4.3 Pentest mission/task contract"

Write-Host "`n[4] Materialize a valid PIP-bound local Pentest task"
$payloadJson = @'
import json
import uuid
from datetime import datetime, timedelta, timezone
from pentest_subsystem.pip_contract import PIP_SCHEMA_VERSION, build_pip_ingestion_binding, seal_pip_artifact
from pentest_subsystem.task_contract import PENTEST_TASK_ARTIFACT_SCHEMA_VERSION, seal_pentest_task_artifact

def z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

now = datetime.now(timezone.utc)
boundary = {
    "pentest_id": f"pentest-{uuid.uuid4()}",
    "mission_id": f"mission-gmo-{uuid.uuid4()}",
    "task_id": f"ptask-{uuid.uuid4()}",
    "scope": {
        "targets": [
            {"target_type": "HOST", "target_value": "lab-a.invalid"},
            {"target_type": "HOST", "target_value": "lab-b.invalid"},
        ],
        "excluded_targets": [{"target_type": "HOST", "target_value": "lab-admin.invalid"}],
        "network_zone": "AUTHORIZED_LAB",
    },
    "objective": {
        "type": "SECURITY_VALIDATION",
        "description": "Stage 4.3 acceptance task contract validation only",
    },
    "constraints": {
        "max_actions": 10,
        "risk_threshold": "MODERATE",
        "data_handling_policy": {"retain_sensitive_output": False},
    },
    "roe": {
        "allowed_action_classes": ["TARGET_RECON", "VULNERABILITY_VALIDATION"],
        "prohibited_action_classes": ["DESTRUCTIVE_ACTION"],
        "destructive_actions_allowed": False,
    },
    "authorization_reference": {
        "policy_decision_id": "decision-stage4-3-acceptance",
        "policy_decision_hash": "b" * 64,
        "policy_version": 1,
        "execution_authorized": True,
        "pre_dispatch_revalidation_id": "xreval-stage4-3-acceptance",
    },
}
pip_core = {
    "schema_version": PIP_SCHEMA_VERSION,
    "pip_id": f"pip-{uuid.uuid4()}",
    "pip_version": "1",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "task_id": boundary["task_id"],
    "source_cti": {
        "source_type": "CTI",
        "source_system": "VULNDESK_CTI",
        "artifact_id": f"cti-{uuid.uuid4()}",
        "artifact_version": "1",
        "artifact_sha256": "c" * 64,
    },
    "issued_at": z(now - timedelta(minutes=5)),
    "expires_at": z(now + timedelta(hours=6)),
    "scope": boundary["scope"],
    "confidence": 0.91,
    "provenance": {
        "producer": "VULNDESK_CTI",
        "source_refs": ["cti-report-stage4-3", "cve-CVE-2026-4242"],
        "collection_method": "CTI_CORRELATION",
        "correlation_id": "corr-stage4-3-acceptance",
    },
    "intelligence": {
        "hypotheses": [{"hypothesis_id": "hyp-001", "summary": "Authorized validation hypothesis"}],
        "observations": [{"kind": "CTI_INDICATOR", "value": "service-family-x"}],
    },
}
pip = seal_pip_artifact(pip_core)
pip_binding = build_pip_ingestion_binding(boundary_payload=boundary, pip_payload=pip, now=now)
target = boundary["scope"]["targets"][0]
task_core = {
    "schema_version": PENTEST_TASK_ARTIFACT_SCHEMA_VERSION,
    "pentest_task_id": f"pentest-task-{uuid.uuid4()}",
    "mission_id": boundary["mission_id"],
    "pentest_id": boundary["pentest_id"],
    "upstream_task_id": boundary["task_id"],
    "pip_reference": {
        "pip_id": pip["pip_id"],
        "pip_version": pip["pip_version"],
        "pip_artifact_sha256": pip["integrity"]["canonical_sha256"],
        "pip_binding_sha256": pip_binding["integrity"]["canonical_sha256"],
    },
    "target": target,
    "scope": {
        "targets": [target],
        "excluded_targets": boundary["scope"]["excluded_targets"],
        "network_zone": boundary["scope"]["network_zone"],
    },
    "objective": boundary["objective"],
    "constraints": boundary["constraints"],
    "evidence_requirement": {
        "minimum_evidence_items": 1,
        "required_artifact_types": ["OBSERVATION", "TRACE"],
        "integrity_required": True,
        "provenance_required": True,
    },
    "authorization_reference": boundary["authorization_reference"],
    "completion_criteria": {
        "all_required": True,
        "criteria": [
            {
                "criterion_id": "criterion-evidence-recorded",
                "type": "EVIDENCE_PRESENT",
                "description": "Required evidence is recorded with provenance and integrity.",
                "required": True,
            },
            {
                "criterion_id": "criterion-scope-preserved",
                "type": "SCOPE_PRESERVED",
                "description": "Declared task scope remains preserved.",
                "required": True,
            },
        ],
    },
    "created_at": z(now),
}
task = seal_pentest_task_artifact(task_core)
print(json.dumps({"boundary": boundary, "pip": pip, "task": task}, separators=(",", ":")))
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "failed to construct canonical Stage 4.3 acceptance payload" }
$taskBody = [string]($payloadJson | Select-Object -Last 1)
$create = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body $taskBody
if ($create.status -ne "created") { throw "task materialization did not return created" }
if (-not $create.created -or -not $create.materialized -or -not $create.persisted) { throw "task materialization/persistence flags incomplete" }
if ($create.binding.schema_version -ne $ExpectedBindingSchema) { throw "task binding schema mismatch" }
if (-not $create.binding.validation.all_required_dimensions_passed) { throw "task binding dimensions did not all pass" }
if (@($create.binding.validation.dimensions).Count -ne 9) { throw "task binding validation dimension count mismatch" }
if ($create.workflow_lifecycle_started) { throw "Stage 4.3 task materialization started lifecycle" }
if ($create.accepted_for_execution) { throw "Stage 4.3 task materialization accepted execution" }
if ($create.authorization_minted) { throw "Stage 4.3 task materialization minted authorization" }
if ($create.tool_invocation_performed) { throw "Stage 4.3 task materialization invoked tools" }
if ($create.target_actuation) { throw "Stage 4.3 task materialization actuated target" }
$taskId = $create.record.pentest_task_id
$missionId = $create.record.mission_id
Write-Host "[PASS] valid PIP-bound local task materialized and persisted without execution"

Write-Host "`n[5] Repository read/query and idempotent replay"
$get = Invoke-RestMethod "$PentestUrl/api/pentest/tasks/$taskId"
if ($get.status -ne "ok") { throw "task get failed" }
if ($get.record.pentest_task_id -ne $taskId) { throw "task get identity mismatch" }
$list = Invoke-RestMethod "$PentestUrl/api/pentest/tasks?mission_id=$missionId"
if ([int]$list.count -lt 1) { throw "mission task query returned no records" }
$replay = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body $taskBody
if ($replay.status -ne "existing") { throw "exact task replay was not idempotent" }
if ($replay.created) { throw "exact task replay incorrectly created a second record" }
Write-Host "[PASS] local repository read/query + exact-idempotent replay"

Write-Host "`n[6] Scope widening negative path"
# Use a deterministic Python subprocess with the original JSON via environment-safe temp file.
$tempPayload = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -Path $tempPayload -Value $taskBody -NoNewline -Encoding UTF8
    $widenedBody = python -c "import json,sys; from pentest_subsystem.task_contract import seal_pentest_task_artifact; p=json.load(open(sys.argv[1],encoding='utf-8-sig')); c={k:v for k,v in p['task'].items() if k!='integrity'}; c['scope']['targets'].append({'target_type':'HOST','target_value':'outside.invalid'}); p['task']=seal_pentest_task_artifact(c); print(json.dumps(p,separators=(',',':')))" $tempPayload
    if ($LASTEXITCODE -ne 0) { throw "failed to construct scope-widening negative payload" }
    $scopeRejected = $false
    try {
        Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/pentest/tasks" -ContentType "application/json" -Body ([string]($widenedBody | Select-Object -Last 1)) -UseBasicParsing | Out-Null
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 400) { $scopeRejected = $true } else { throw }
    }
    if (-not $scopeRejected) { throw "scope widening was not rejected with HTTP 400" }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $tempPayload
}
Write-Host "[PASS] scope widening fails closed"

Write-Host "`n[7] Execution-intake negative boundary"
$dispatchRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) { $dispatchRejected = $true } else { throw }
}
if (-not $dispatchRejected) { throw "Stage 4.3 execution dispatch was not rejected with HTTP 409" }
Write-Host "[PASS] execution dispatch remains disabled"

Write-Host "`n[8] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[9] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[10] Focused Stage 4.3 regression"
python -m pytest -q tests/test_stage4_3_pentest_mission_task_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.3 focused regression failed" }

Write-Host "`n[11] Stage 4.1 + 4.2 + critical predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py `
  tests/test_stage4_3_pentest_mission_task_contract.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.3 critical predecessor regression failed" }

Write-Host "`n[12] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.3 Pentest Mission & Task Contract"
Write-Host "control_version  : $ExpectedControl"
Write-Host "mission migration: $ExpectedMissionMigration"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.2 PIP Ingestion, Validation & Binding"
Write-Host "repository       : isolated durable local Pentest task contract store"
Write-Host "semantics        : task materialization only; no lifecycle; no execution; no actuation"
Write-Host "next             : Stage 4.4 - Pentest Lifecycle & State"
Write-Host "=============================================================================="
