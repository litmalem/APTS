param(
    [string]$MissionUrl = "http://127.0.0.1:8780",
    [string]$PentestUrl = "http://127.0.0.1:8790"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$ExpectedMissionControl = "stage3.9.10-global-mission-orchestrator-acceptance-regression-gate"
$ExpectedBoundaryControl = "stage4.1-pentest-boundary-canonical-contract"
$ExpectedControl = "stage4.2-pip-ingestion-validation-binding"
$ExpectedSchema = "apts-stage4.2-pip-ingestion-validation-binding-v1"
$ExpectedPipSchema = "apts-pentest-intelligence-package-v1"
$ExpectedBindingSchema = "apts-stage4.2-pip-ingestion-binding-envelope-v1"
$ExpectedMissionMigration = 53
$ExpectedPentestMigration = 0
$ExpectedInventory = 1605

Write-Host "=============================================================================="
Write-Host "Stage 4.2 - PIP Ingestion, Validation & Binding"
Write-Host "=============================================================================="

Write-Host "`n[0] Stage 3 predecessor preflight"
$mo = Invoke-RestMethod "$MissionUrl/health"
if ($mo.control_version -ne $ExpectedMissionControl) { throw "Mission Orchestrator predecessor control mismatch: $($mo.control_version)" }
if ([int]$mo.mission_repository_migration_level -ne $ExpectedMissionMigration) { throw "Mission Orchestrator migration mismatch" }
if ($mo.stage3_9_10_stage_output -ne "GLOBAL_MISSION_ORCHESTRATOR") { throw "Stage 3 output mismatch" }
Write-Host "[PASS] Stage 3.9.10 remains closed"

Write-Host "`n[1] Stage 4.2 Pentest runtime activation preflight"
$health = Invoke-RestMethod "$PentestUrl/health"
if ($health.status -ne "ok") { throw "Pentest subsystem health is not ok" }
if ($health.subsystem_id -ne "PENTEST") { throw "Pentest subsystem identity mismatch" }
if ($health.control_version -ne $ExpectedControl) { throw "Pentest control mismatch: $($health.control_version)" }
if ([int]$health.pentest_repository_migration_level -ne $ExpectedPentestMigration) { throw "Pentest repository migration must remain 0" }
if ($health.stage4_2_schema_version -ne $ExpectedSchema) { throw "Stage 4.2 schema mismatch" }
if ($health.stage4_2_pip_schema_version -ne $ExpectedPipSchema) { throw "PIP schema mismatch" }
if ($health.stage4_2_binding_envelope_schema_version -ne $ExpectedBindingSchema) { throw "PIP binding schema mismatch" }
if ($health.stage4_2_predecessor_control -ne $ExpectedBoundaryControl) { throw "Stage 4.2 predecessor mismatch" }
if (-not $health.stage4_2_pip_ingestion_enabled) { throw "Stage 4.2 PIP ingestion is not enabled" }
if (-not $health.stage4_2_binding_enabled) { throw "Stage 4.2 PIP binding is not enabled" }
if ($health.stage4_2_source_cti_query_performed) { throw "Stage 4.2 must not query CTI externally" }
if ($health.stage4_2_execution_intake_enabled) { throw "Stage 4.2 must not enable execution intake" }
if ($health.stage4_2_workflow_runtime_enabled) { throw "Stage 4.2 must not enable workflow runtime" }
if ($health.stage4_2_local_task_repository_enabled) { throw "Stage 4.2 must not enable local task repository" }
if ($health.stage4_2_durable_persistence_enabled) { throw "Stage 4.2 must not add durable persistence" }
if ($health.stage4_2_tool_invocation_enabled) { throw "Stage 4.2 must not invoke Pentest tools" }
if ($health.stage4_2_target_actuation) { throw "Stage 4.2 must not actuate targets" }
if ($health.stage4_2_next_stage -ne "4.3") { throw "Stage 4.2 next-stage mismatch" }
if (@($health.stage4_2_validation_dimensions).Count -ne 8) { throw "Stage 4.2 validation-dimension count mismatch" }
Write-Host "[PASS] Stage 4.2 runtime active and non-executing"

Write-Host "`n[2] Stage 4.1 canonical predecessor remains available"
$boundaryContract = Invoke-RestMethod "$PentestUrl/api/pentest/boundary-contract"
if ($boundaryContract.control_version -ne $ExpectedBoundaryControl) { throw "Stage 4.1 boundary contract control mismatch" }
if ($boundaryContract.active_control_version -ne $ExpectedControl) { throw "boundary route active-control mismatch" }
if ($boundaryContract.execution_intake_enabled) { throw "Stage 4.1 boundary route incorrectly enables execution" }
if ($boundaryContract.target_actuation) { throw "Stage 4.1 boundary route incorrectly enables target actuation" }
Write-Host "[PASS] canonical Stage 4.1 boundary predecessor preserved"

Write-Host "`n[3] Canonical Stage 4.2 PIP contract API"
$pipContract = Invoke-RestMethod "$PentestUrl/api/pentest/pip-contract"
if ($pipContract.control_version -ne $ExpectedControl) { throw "PIP contract route control mismatch" }
if ($pipContract.definition.schema_version -ne $ExpectedSchema) { throw "PIP contract definition schema mismatch" }
if ($pipContract.definition.pip_schema_version -ne $ExpectedPipSchema) { throw "PIP artifact schema mismatch" }
if ($pipContract.definition.binding_envelope_schema_version -ne $ExpectedBindingSchema) { throw "PIP binding envelope schema mismatch" }
if ($pipContract.definition.predecessor_control -ne $ExpectedBoundaryControl) { throw "PIP predecessor mismatch" }
if (@($pipContract.definition.validation_dimensions).Count -ne 8) { throw "PIP validation dimension mismatch" }
if (-not $pipContract.pip_is_intelligence_input) { throw "PIP must be declared intelligence input" }
if ($pipContract.pip_is_execution_command) { throw "PIP must not be declared execution command" }
if ($pipContract.execution_intake_enabled) { throw "PIP contract incorrectly enables execution" }
if ($pipContract.durable_persistence_enabled) { throw "PIP contract incorrectly enables persistence" }
if ($pipContract.target_actuation) { throw "PIP contract incorrectly enables target actuation" }
Write-Host "[PASS] canonical Stage 4.2 PIP contract"

Write-Host "`n[4] Valid PIP ingestion / validation / exact binding"
$payloadJson = @'
import json
import uuid
from datetime import datetime, timedelta, timezone
from pentest_subsystem.pip_contract import PIP_SCHEMA_VERSION, seal_pip_artifact

def z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

now = datetime.now(timezone.utc)
boundary = {
    "pentest_id": f"pentest-{uuid.uuid4()}",
    "mission_id": f"mission-gmo-{uuid.uuid4()}",
    "task_id": f"ptask-{uuid.uuid4()}",
    "scope": {
        "targets": [{"target_type": "HOST", "target_value": "lab-target.invalid"}],
        "excluded_targets": [],
    },
    "objective": {
        "type": "SECURITY_VALIDATION",
        "description": "Stage 4.2 acceptance PIP validation only",
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
        "policy_decision_id": "decision-stage4-2-acceptance",
        "policy_decision_hash": "b" * 64,
        "policy_version": 1,
        "execution_authorized": True,
        "pre_dispatch_revalidation_id": "xreval-stage4-2-acceptance",
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
        "source_refs": ["cti-report-stage4-2", "cve-CVE-2026-4242"],
        "collection_method": "CTI_CORRELATION",
        "correlation_id": "corr-stage4-2-acceptance",
    },
    "intelligence": {
        "hypotheses": [{"hypothesis_id": "hyp-001", "summary": "Authorized validation hypothesis"}],
        "observations": [{"kind": "CTI_INDICATOR", "value": "service-family-x"}],
    },
}
print(json.dumps({"boundary": boundary, "pip": seal_pip_artifact(pip_core)}, separators=(",", ":")))
'@ | python -
if ($LASTEXITCODE -ne 0) { throw "failed to construct canonical PIP acceptance payload" }
$ingestBody = [string]($payloadJson | Select-Object -Last 1)
$ingest = Invoke-RestMethod -Method Post -Uri "$PentestUrl/api/pentest/pip/ingest" -ContentType "application/json" -Body $ingestBody
if ($ingest.status -ne "valid") { throw "PIP ingestion did not return valid" }
if (-not $ingest.ingested -or -not $ingest.validated -or -not $ingest.bound) { throw "PIP ingestion/validation/binding flags incomplete" }
if (-not $ingest.intelligence_input_only) { throw "PIP result not marked intelligence-only" }
if ($ingest.accepted_for_execution) { throw "PIP ingestion accepted execution" }
if ($ingest.pentest_task_materialized) { throw "PIP ingestion materialized Pentest task" }
if ($ingest.workflow_materialized) { throw "PIP ingestion materialized workflow" }
if ($ingest.persisted) { throw "PIP ingestion persisted durable state" }
if ($ingest.authorization_minted) { throw "PIP ingestion minted authorization" }
if ($ingest.tool_invocation_performed) { throw "PIP ingestion invoked tools" }
if ($ingest.target_actuation) { throw "PIP ingestion actuated target" }
if ($ingest.binding.schema_version -ne $ExpectedBindingSchema) { throw "PIP binding envelope schema mismatch" }
if (-not $ingest.binding.validation.all_required_dimensions_passed) { throw "PIP validation dimensions did not all pass" }
if (@($ingest.binding.validation.dimensions).Count -ne 8) { throw "PIP binding validation dimension count mismatch" }
Write-Host "[PASS] PIP ingested, validated, and bound without execution/persistence"

Write-Host "`n[5] Tamper negative path"
$tampered = $ingestBody | ConvertFrom-Json
$tampered.pip.intelligence.observations[0].value = "tampered-after-integrity"
$tamperedBody = $tampered | ConvertTo-Json -Depth 50 -Compress
$tamperRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/pentest/pip/ingest" -ContentType "application/json" -Body $tamperedBody -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 400) {
        $tamperRejected = $true
    } else {
        throw
    }
}
if (-not $tamperRejected) { throw "tampered PIP was not rejected with HTTP 400" }
Write-Host "[PASS] tampered PIP fails closed"

Write-Host "`n[6] Execution-intake negative boundary"
$dispatchRejected = $false
try {
    Invoke-WebRequest -Method Post -Uri "$PentestUrl/api/execution/dispatches" -ContentType "application/json" -Body '{"probe":true}' -UseBasicParsing | Out-Null
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        $dispatchRejected = $true
    } else {
        throw
    }
}
if (-not $dispatchRejected) { throw "Stage 4.2 execution dispatch was not rejected with HTTP 409" }
Write-Host "[PASS] execution dispatch remains disabled"

Write-Host "`n[7] Python compilation"
python -m compileall -q mission_orchestrator pentest_subsystem run tests
if ($LASTEXITCODE -ne 0) { throw "Python compilation failed" }
Write-Host "[PASS] Python compilation"

Write-Host "`n[8] Canonical test inventory"
$collect = python -m pytest --collect-only -q
if ($LASTEXITCODE -ne 0) { throw "pytest collection failed" }
$summary = $collect | Select-Object -Last 1
if ($summary -notmatch "^$ExpectedInventory tests collected") { throw "expected $ExpectedInventory tests, got: $summary" }
Write-Host "[PASS] $ExpectedInventory tests collected"

Write-Host "`n[9] Focused Stage 4.2 regression"
python -m pytest -q tests/test_stage4_2_pip_ingestion_validation_binding.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.2 focused regression failed" }

Write-Host "`n[10] Stage 4.1 + critical predecessor regression"
python -m pytest -q `
  tests/test_stage3_9_10_global_mission_orchestrator_acceptance_regression_gate.py `
  tests/test_stage3_4_1_canonical_subsystem_registry_capability_contract.py `
  tests/test_stage3_2_3_mission_pip_activation.py `
  tests/test_stage3_1_3_scope_roe_constraint_contract.py `
  tests/test_stage4_1_pentest_boundary_canonical_contract.py `
  tests/test_stage4_2_pip_ingestion_validation_binding.py
if ($LASTEXITCODE -ne 0) { throw "Stage 4.2 critical predecessor regression failed" }

Write-Host "`n[11] Full historical regression - FINAL PASS/FAIL AUTHORITY"
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "full historical regression failed" }

Write-Host "`n=============================================================================="
Write-Host "[PASS] Stage 4.2 PIP Ingestion, Validation & Binding"
Write-Host "control_version  : $ExpectedControl"
Write-Host "pentest migration: $ExpectedPentestMigration"
Write-Host "inventory        : $ExpectedInventory"
Write-Host "predecessor      : Stage 4.1 Pentest Boundary & Canonical Contract"
Write-Host "validation       : identity / mission / CTI / freshness / integrity / scope / confidence / provenance"
Write-Host "semantics        : intelligence input only; no execution; no persistence; no actuation"
Write-Host "next             : Stage 4.3 - Pentest Mission & Task Contract"
Write-Host "=============================================================================="
